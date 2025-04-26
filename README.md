# GSheet Auto - Article Processor and Organizer.

A web application that processes news articles, checks their relevance based on category tags, and organizes them into Google Sheets. The system includes a crawler for finding relevant articles and a sophisticated article processor for extracting and summarizing content.

## Features

- **Article Processing**: Extract and summarize content from news articles using TextRank algorithm
- **Content Relevance Checking**: Verify if articles contain keywords relevant to specific categories
- **Google Sheets Integration**: Store relevant articles in categorized sheets
- **Web Crawler**: Find articles from defined publishers related to specific topics
- **Unused Article Management**: Track and manage articles that don't match relevance criteria

## Setup

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Place your Google Sheets API credentials in a file named `credentials.json`
4. Run the application:
   ```
   python app.py
   ```

## API Endpoints

### Article Processing

- `POST /scrape-article` - Extract and process a single article
  ```json
  {
    "url": "https://example.com/article",
    "category": "AI Policy",
    "publisher": "Example Publisher"
  }
  ```

- `POST /scrape-articles-batch` - Process multiple articles at once
  ```json
  {
    "articles": [
      {
        "url": "https://example.com/article1",
        "category": "AI Policy",
        "publisher": "Example Publisher"
      },
      {
        "url": "https://example.com/article2",
        "category": "AI Governance",
        "publisher": "Another Publisher"
      }
    ]
  }
  ```

### Unused Links Management

- `GET /unused-links` - Get all links that didn't match category tags
- `DELETE /unused-links` - Delete unused links based on filters
  ```json
  {
    "category": "AI Policy",
    "publisher": "Example Publisher",
    "before_date": "2023-01-01T00:00:00",
    "all": false
  }
  ```
- `POST /unused-links/recover` - Recover an unused link and add it to Google Sheets
  ```json
  {
    "url": "https://example.com/article",
    "category": "AI Policy",
    "summary": "Optional custom summary",
    "title": "Optional custom title"
  }
  ```

### Google Sheets Management

- `GET /worksheets` - List all worksheets
- `POST /create-worksheet` - Create a new worksheet
- `POST /delete-worksheet` - Delete a worksheet
- `POST /add-link` - Add a link to a worksheet
- `GET /worksheet-data?name=SheetName` - Get data from a specific worksheet

### Crawler Settings

- `GET /crawler-settings` - Get crawler settings
- `POST /crawler-settings` - Add or update a publisher
- `DELETE /crawler-settings/{category}/{publisher}` - Remove a publisher
- `GET /crawler-settings/tags/{category}` - Get tags for a category
- `PUT /crawler-settings/tags/{category}` - Update tags for a category

## How It Works

### Article Processing

The system extracts content from articles using two methods:
1. **Primary method**: Uses newspaper3k to parse article content
2. **Fallback method**: Uses BeautifulSoup with randomized user agents

After extraction, the article is summarized using the TextRank algorithm, which:
1. Breaks text into sentences
2. Creates a similarity matrix between sentences
3. Uses PageRank to identify the most important sentences
4. Assembles top sentences into a coherent summary

### Relevance Checking

For each article:
1. The system loads tags associated with the article's category
2. Checks if any tags are present in the article text
3. If matching tags are found, the article is considered relevant
4. Relevant articles are added to Google Sheets, while irrelevant ones are saved to `unused_links.json`

## Configuration

- `crawler_settings.json`: Contains publisher information and category tags
- `config.json`: Contains the Google Sheet ID
- `crawled_links.json`: Stores links found by the crawler
- `unused_links.json`: Stores links that didn't match relevance criteria

## 🌟 Features Overview

### For Everyone
- **Easy Resource Management**: Add and organize AI governance resources with just a few clicks
- **Smart Article Scraping**: Automatically extracts titles and summaries from articles
- **Beautiful Interface**: Clean, modern design with light and dark theme support
- **Simple Organization**: Create and manage different worksheets for different topics
- **Google Sheets Integration**: All your resources are stored in your own Google Sheet
- **One-Click Access**: View your Google Sheet directly from the application

### For Technical Users
- **RESTful API**: Built with Flask for robust backend functionality
- **Google Sheets API Integration**: Secure connection to Google Sheets
- **Article Scraping**: Advanced web scraping capabilities with fallback mechanisms
- **Responsive Design**: Works seamlessly on desktop and mobile devices
- **Theme Persistence**: Saves your preferred theme (light/dark) across sessions
- **Error Handling**: Comprehensive error handling and user feedback

## 🚀 Getting Started

### Prerequisites
- Python 3.7 or higher
- Google Cloud Platform account
- Google Sheets API enabled
- Service account credentials

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/ai-governance-resource-manager.git
   cd ai-governance-resource-manager
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Google Sheets API**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project
   - Enable Google Sheets API
   - Create service account credentials
   - Download the credentials JSON file
   - Rename it to `credentials.json` and place it in the project root

4. **Configure the application**
   - Create a new Google Sheet
   - Copy the Sheet ID from the URL
   - The Sheet ID is the long string between `/d/` and `/edit` in the URL
   - Add the Sheet ID to `config.json`

5. **Run the application**
   ```bash
   python app.py
   ```
   The application will be available at `http://localhost:5000`

## 📝 User Guide

### Adding Resources
1. Click on the "Add Resource" tab
2. Paste the URL of the article or resource
3. The application will automatically fetch the title and summary
4. Select a worksheet to categorize the resource
5. Click "Add Resource" to save

### Managing Worksheets
1. Click on the "Manage Worksheets" tab
2. To create a new worksheet:
   - Enter a descriptive name
   - Click "Create Worksheet"
3. To change the Google Sheet:
   - Enter the new Sheet ID
   - Click "Update ID"
   - Confirm the change in the popup

### Viewing Your Sheet
- Click the "View Sheet" button to open your Google Sheet in a new tab
- All your resources will be organized in the worksheets you created

## 🔧 Technical Details

### Project Structure
```
ai-governance-resource-manager/
├── app.py              # Main Flask application
├── config.json         # Configuration file
├── credentials.json    # Google Sheets API credentials
├── requirements.txt    # Python dependencies
├── static/            # Static files (CSS, JS, images)
└── templates/         # HTML templates
    └── index.html     # Main application template
```

### API Endpoints
- `GET /` - Main application page
- `GET /worksheets` - List all worksheets
- `POST /add-link` - Add a new resource
- `GET /sheet-info` - Get sheet information
- `POST /create-worksheet` - Create a new worksheet
- `POST /update-sheet-id` - Update the Google Sheet ID
- `POST /scrape-article` - Scrape article content

### Dependencies
- Flask - Web framework
- gspread - Google Sheets API client
- newspaper3k - Article scraping
- requests - HTTP requests
- beautifulsoup4 - HTML parsing

## 🛠️ Development

### Running Tests
```bash
python -m pytest
```

### Code Style
The project follows PEP 8 style guidelines. Use the following command to check:
```bash
flake8 .
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## 📚 Non-Technical Guide

### What is this tool?
This is a simple web application that helps you organize and manage AI governance resources. Think of it as a smart bookmark manager that automatically saves important information from articles and websites.

### Why use this tool?
- **Save Time**: Automatically extracts titles and summaries from articles
- **Stay Organized**: Keep all your resources in one place
- **Easy Access**: View and manage your resources from anywhere
- **Custom Categories**: Create different sections for different topics
- **Beautiful Interface**: Easy to use with a clean, modern design

### How to use it (Step by Step)

#### 1. Getting Started
- Open the application in your web browser
- You'll see two main sections: "Add Resource" and "Manage Worksheets"

#### 2. Adding a New Resource
- Click on "Add Resource"
- Paste the URL of an article or website
- The tool will automatically fill in the title and summary
- Choose a category (worksheet) for the resource
- Click "Add Resource" to save

#### 3. Creating Categories
- Click on "Manage Worksheets"
- Enter a name for your new category (e.g., "AI Ethics", "Regulations")
- Click "Create Worksheet"
- Your new category is ready to use

#### 4. Viewing Your Resources
- Click the "View Sheet" button to see all your saved resources
- Resources are organized by category
- Each entry shows the title, summary, and date

#### 5. Changing Themes
- Use the theme switch in the top-right corner
- Choose between light and dark mode
- Your preference will be saved

### Tips for Best Use
- Create specific categories for different topics
- Use descriptive names for your worksheets
- Regularly review and organize your resources
- Take advantage of the automatic title and summary feature
- Use the dark theme for reduced eye strain

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Support
For support, please open an issue in the GitHub repository or contact the maintainers.

## 🙏 Acknowledgments
- Google Sheets API
- Flask Framework
- All contributors and users 