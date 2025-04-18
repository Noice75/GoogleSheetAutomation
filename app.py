from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import os
import logging
from newspaper import Article
import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import time
import random

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all domains

# Google Sheets API setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
try:
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)

    # Replace with your actual Google Sheet ID
    SHEET_ID = "1_bxDix9ytq7IYMxUA6PI7obyKJCHrnpN5yLXuJb1AfY"
    sheet = client.open_by_key(SHEET_ID)
    logger.info(f"Successfully connected to Google Sheet: {SHEET_ID}")
except Exception as e:
    logger.error(f"Error initializing Google Sheets API: {str(e)}")

# Helper function to reconnect if token expires
def reconnect_if_needed():
    global client, sheet
    try:
        # Try to access the sheet to check if credentials are still valid
        sheet.worksheets()
        return True
    except Exception as e:
        logger.warning(f"Connection error, attempting to reconnect: {str(e)}")
        try:
            # Reconnect
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_key(SHEET_ID)
            logger.info("Reconnected to Google Sheets successfully")
            return True
        except Exception as reconnect_error:
            logger.error(f"Failed to reconnect: {str(reconnect_error)}")
            return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return '', 204  # Suppress 404 for favicon requests

@app.route('/worksheets')
def list_worksheets():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheets = sheet.worksheets()
        worksheet_names = [ws.title for ws in worksheets]
        logger.info(f"Retrieved {len(worksheet_names)} worksheets")
        return jsonify({"worksheets": worksheet_names}), 200
    except Exception as e:
        logger.error(f"Error listing worksheets: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/sheet-info')
def sheet_info():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet("Sheet1")
        values = worksheet.get_all_values()
        headers = []
        if values:
            # The first row should be considered headers
            headers = values[0]
            data_rows = values[1:] if len(values) > 1 else []
        return jsonify({
            "headers": headers, 
            "row_count": len(values),
            "data_rows": len(data_rows) if 'data_rows' in locals() else 0
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving sheet info: {str(e)}")
        return jsonify({"error": str(e)}), 500
    
# Add this new endpoint to your Flask application
@app.route('/get-sheet-id')
def get_sheet_id():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        # Return the sheet ID from the server
        return jsonify({
            "status": "success", 
            "sheet_id": SHEET_ID
        }), 200
    except Exception as e:
        logger.error(f"Error retrieving sheet ID: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route("/add-link", methods=["POST"])
def add_link():
    try:
        data = request.json
        tab_name = data.get("category")
        link = data.get("link")
        summary = data.get("summary", "")
        date = data.get("date", datetime.today().strftime("%m/%d/%Y"))
        
        if not tab_name or not link:
            return jsonify({"error": "Worksheet name and link are required"}), 400
            
        # Validate URL (basic validation)
        if not link.startswith(('http://', 'https://')):
            return jsonify({"error": "URL must start with http:// or https://"}), 400
        
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet(tab_name)
        
        # Only add the data row
        worksheet.append_row([link, summary, date])
        logger.info(f"Added link to worksheet '{tab_name}': {link[:50]}...")
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Error adding link: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/reset-sheet')
def reset_sheet():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet("Sheet1")
        # Clear the sheet
        worksheet.clear()
        # Add headers
        worksheet.append_row(["Link", "Summary", "Date"])
        logger.info("Reset Sheet1 with headers")
        return jsonify({"status": "Sheet reset with headers"}), 200
    except Exception as e:
        logger.error(f"Error resetting sheet: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get-worksheets')
def get_worksheets():
    try:
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheets = sheet.worksheets()
        worksheet_names = [ws.title for ws in worksheets]
        logger.info(f"Retrieved {len(worksheet_names)} worksheets")
        return jsonify({"worksheets": worksheet_names}), 200
    except Exception as e:
        logger.error(f"Error getting worksheets: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/worksheet-data')
def get_worksheet_data():
    try:
        name = request.args.get('name')
        if not name:
            return jsonify({"error": "Worksheet name is required"}), 400
            
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        worksheet = sheet.worksheet(name)
        values = worksheet.get_all_values()
        
        # Skip the header row if it exists
        rows = values[1:] if len(values) > 0 else []
        
        logger.info(f"Retrieved {len(rows)} rows from worksheet '{name}'")
        return jsonify({"status": "success", "rows": rows}), 200
    except Exception as e:
        logger.error(f"Error getting worksheet data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/create-worksheet', methods=["POST"])
def create_worksheet():
    try:
        data = request.json
        new_title = data.get('title')
        
        if not new_title:
            return jsonify({"error": "Worksheet title is required"}), 400
            
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        # Check if worksheet already exists
        existing_worksheets = [ws.title for ws in sheet.worksheets()]
        if new_title in existing_worksheets:
            return jsonify({"error": f"Worksheet '{new_title}' already exists"}), 400
            
        # Create new worksheet
        new_worksheet = sheet.add_worksheet(title=new_title, rows=1, cols=4)
        
        # Add headers to new worksheet
        new_worksheet.append_row(["Link", "Summary", "Date"])
        
        logger.info(f"Created new worksheet: '{new_title}'")
        return jsonify({"status": "success", "message": f"Worksheet '{new_title}' created"}), 201
    except Exception as e:
        logger.error(f"Error creating worksheet: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/delete-worksheet', methods=["POST"])
def delete_worksheet():
    try:
        data = request.json
        worksheet_name = data.get('name')
        
        if not worksheet_name:
            return jsonify({"error": "Worksheet name is required"}), 400
            
        if not reconnect_if_needed():
            return jsonify({"error": "Could not connect to Google Sheets"}), 500
            
        # Don't allow deleting the default Sheet1
        if worksheet_name.lower() == "sheet1":
            return jsonify({"error": "Cannot delete the default worksheet"}), 400
            
        # Find the worksheet by name
        worksheets = sheet.worksheets()
        worksheet_to_delete = None
        
        for ws in worksheets:
            if ws.title == worksheet_name:
                worksheet_to_delete = ws
                break
                
        if not worksheet_to_delete:
            return jsonify({"error": f"Worksheet '{worksheet_name}' not found"}), 404
            
        # Delete the worksheet
        sheet.del_worksheet(worksheet_to_delete)
        
        logger.info(f"Deleted worksheet: '{worksheet_name}'")
        return jsonify({"status": "success", "message": f"Worksheet '{worksheet_name}' deleted"}), 200
    except Exception as e:
        logger.error(f"Error deleting worksheet: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health_check():
    """Simple health check endpoint"""
    try:
        if reconnect_if_needed():
            return jsonify({"status": "healthy", "message": "Application is running correctly"}), 200
        else:
            return jsonify({"status": "unhealthy", "message": "Cannot connect to Google Sheets"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/scrape-article', methods=['POST'])
def scrape_article():
    try:
        data = request.json
        url = data.get('url')
        
        if not url:
            return jsonify({"error": "URL is required"}), 400
            
        # First try with simple newspaper approach
        try:
            article = Article(url)
            article.download()
            article.parse()
            
            if article.text:
                formatted_summary = f"Title: {article.title}\n\nSummary: {article.text[:500]}..."
                return jsonify({
                    "status": "success",
                    "title": article.title,
                    "summary": formatted_summary
                }), 200
        except Exception as e:
            logger.warning(f"Initial scraping attempt failed: {str(e)}")
            # Continue to fallback method if first attempt fails
        
        # If first attempt fails, try with user agent and fallback methods
        try:
            ua = UserAgent()
            headers = {
                'User-Agent': ua.random,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
            
            # Try direct requests with BeautifulSoup
            response = requests.get(url, headers=headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to get title
            title = soup.title.string if soup.title else "No title found"
            
            # Try to get main content
            main_content = soup.find('main') or soup.find('article') or soup.find('div', class_='content')
            if main_content:
                text = main_content.get_text(strip=True)
            else:
                # Fallback to body text
                text = soup.body.get_text(strip=True) if soup.body else "No content found"
            
            formatted_summary = f"Title: {title}\n\nSummary: {text[:500]}..."
            
            return jsonify({
                "status": "success",
                "title": title,
                "summary": formatted_summary
            }), 200
            
        except Exception as fallback_error:
            logger.error(f"Fallback scraping failed: {str(fallback_error)}")
            return jsonify({"error": "Could not scrape the article. The website might be blocking automated access."}), 500
                
    except Exception as e:
        logger.error(f"Error scraping article: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)