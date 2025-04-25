import requests
from newspaper import Article, Config
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import json
import os
import logging
from datetime import datetime
import string
from urllib.parse import urlparse
import re

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ArticleProcessor:
    def __init__(self):
        # File paths
        self.crawler_settings_path = 'crawler_settings.json'
        self.unused_links_path = 'unused_links.json'
        
    def load_crawler_settings(self):
        """Load crawler settings from crawler_settings.json"""
        if not os.path.exists(self.crawler_settings_path):
            # Create default settings file
            default_settings = {
                "categories": {}
            }
            with open(self.crawler_settings_path, 'w') as f:
                json.dump(default_settings, f, indent=4)
            return default_settings
        
        with open(self.crawler_settings_path, 'r') as f:
            settings = json.load(f)
            
            # Check if settings needs to be migrated to new format
            if "categories" not in settings:
                # Old format, convert to new format
                new_settings = {"categories": {}}
                for category, publishers in settings.items():
                    new_settings["categories"][category] = {
                        "tags": ["ai governance", "ai policy"],  # Default tags
                        "publishers": publishers
                    }
                settings = new_settings
                # Save the migrated settings
                self._save_crawler_settings(settings)
                
            return settings
    
    def identify_publisher(self, url):
        """
        Try to identify the publisher based on the URL by checking against crawler_settings.json
        Returns: (publisher_name, category) or (None, None) if not found
        """
        if not url:
            return None, None
            
        try:
            # Parse the URL to get the domain
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            
            # Remove www. from the beginning if present
            if domain.startswith('www.'):
                domain = domain[4:]
                
            # Load the crawler settings
            settings = self.load_crawler_settings()
            
            # Check each category's publishers
            for category_name, category_data in settings.get("categories", {}).items():
                for publisher_name, publisher_url in category_data.get("publishers", {}).items():
                    # Parse the publisher URL to get the domain
                    parsed_publisher_url = urlparse(publisher_url)
                    publisher_domain = parsed_publisher_url.netloc.lower()
                    
                    # Remove www. from the beginning if present
                    if publisher_domain.startswith('www.'):
                        publisher_domain = publisher_domain[4:]
                    
                    # Check if the URL's domain matches the publisher's domain
                    if domain == publisher_domain or domain.endswith('.' + publisher_domain) or publisher_domain.endswith('.' + domain):
                        return publisher_name, category_name
            
            # If no match is found, try a more lenient approach
            for category_name, category_data in settings.get("categories", {}).items():
                for publisher_name, publisher_url in category_data.get("publishers", {}).items():
                    # Parse the publisher URL to get the domain
                    parsed_publisher_url = urlparse(publisher_url)
                    publisher_domain = parsed_publisher_url.netloc.lower()
                    
                    # Remove www. from the beginning if present
                    if publisher_domain.startswith('www.'):
                        publisher_domain = publisher_domain[4:]
                    
                    # Check if the domain contains recognizable parts of the publisher name
                    publisher_name_lower = publisher_name.lower()
                    if publisher_name_lower in domain or any(part in domain for part in publisher_name_lower.split()):
                        return publisher_name, category_name
            
            # No match found
            return None, None
                
        except Exception as e:
            logger.warning(f"Error identifying publisher from URL {url}: {str(e)}")
            return None, None
            
    def _save_crawler_settings(self, settings):
        """Save crawler settings to crawler_settings.json"""
        with open(self.crawler_settings_path, 'w') as f:
            json.dump(settings, f, indent=4)
        return True
    
    def save_unused_link(self, url, category, publisher=None, reason=None):
        """Save link to unused_links.json when it doesn't contain relevant tags"""
        if not os.path.exists(self.unused_links_path):
            unused_links = []
        else:
            try:
                with open(self.unused_links_path, 'r') as f:
                    unused_links = json.load(f)
            except json.JSONDecodeError:
                unused_links = []
        
        # Check if link already exists
        for link in unused_links:
            if isinstance(link, dict) and link.get('url') == url:
                return False
        
        # Add new entry
        entry = {
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "publisher": publisher,
            "reason": reason
        }
        
        unused_links.append(entry)
        
        with open(self.unused_links_path, 'w') as f:
            json.dump(unused_links, f, indent=4)
            
        return True
    
    def extract_article_content(self, url):
        """Extract article content using newspaper3k"""
        if not url:
            return None, None, "URL is required"
            
        try:
            # Configure newspaper with better settings
            config = Config()
            config.browser_user_agent = UserAgent().random
            config.request_timeout = 15
            config.memoize_articles = False  # Disable caching for fresh results
            
            # Create article with the custom config
            article = Article(url, config=config)
            article.download()
            article.parse()
            
            # Check if we got meaningful content
            if not article.text or len(article.text.strip()) < 20:
                raise ValueError("Not enough content extracted")
                
            # Try to get article metadata
            try:
                article.nlp()
            except Exception as nlp_err:
                logger.warning(f"Error performing NLP on article: {str(nlp_err)}")
            
            # Get the publish date if available
            publish_date = None
            if article.publish_date:
                publish_date = article.publish_date.isoformat()
            
            # Extract and save article metadata
            metadata = {
                "authors": article.authors,
                "publish_date": publish_date,
                "top_image": article.top_image,
                "keywords": article.keywords if hasattr(article, 'keywords') else [],
                "summary": article.summary if hasattr(article, 'summary') else ""
            }
            
            # Log successful extraction
            logger.info(f"Successfully extracted article from {url} using newspaper3k")
            
            return article.title, article.text, None
            
        except Exception as e:
            logger.error(f"Article extraction failed: {str(e)}")
            return None, None, f"Could not extract the article: {str(e)}"
    
    def summarize_article(self, text, max_length=200):
        """
        Create a very concise summary using newspaper3k or simple truncation.
        Just 2-3 lines maximum to attract readers.
        """
        if not text:
            return ""
        
        # Use simple truncation for consistent, brief summaries
        # This ensures we don't need complex NLP for summarization
        first_para = text.split('\n\n')[0]
        
        if len(first_para) > max_length:
            return first_para[:max_length] + "..."
        return first_para
    
    def check_article_relevance(self, category, text):
        """Check if article contains any of the tags for the given category"""
        if not category or not text:
            return False, "Missing category or text"
            
        settings = self.load_crawler_settings()
        
        # Get tags for the category
        if "categories" not in settings or category not in settings["categories"]:
            return False, f"Category '{category}' not found in settings"
            
        tags = settings["categories"][category].get("tags", [])
        
        if not tags:
            # If no tags defined, consider it relevant
            return True, None
            
        # Convert text to lowercase for case-insensitive matching
        text_lower = text.lower()
        
        # Check if any tag is present in the text
        matched_tags = []
        for tag in tags:
            if tag.lower() in text_lower:
                matched_tags.append(tag)
                
        if matched_tags:
            return True, matched_tags
        else:
            return False, f"None of the tags {tags} found in the article"
    
    def process_article(self, url, category, publisher=None):
        """Full process: extract, check relevance, and summarize if relevant"""
        # Extract content
        title, text, error = self.extract_article_content(url)
        
        if error:
            return {
                "status": "error",
                "error": error
            }
            
        # If no publisher provided, try to identify it from the URL
        identified_publisher = None
        identified_category = None
        if not publisher:
            identified_publisher, identified_category = self.identify_publisher(url)
            if identified_publisher:
                publisher = identified_publisher
                
        # If no category provided but we identified one from the publisher, use that
        if not category and identified_category:
            category = identified_category
            
        # If we still don't have a category, we can't check relevance
        if not category:
            return {
                "status": "error",
                "error": "Category is required to check article relevance",
                "title": title,
                "publisher_required": True,
                "identified_publisher": identified_publisher,
                "url": url
            }
            
        # Check relevance based on category tags
        is_relevant, relevance_info = self.check_article_relevance(category, text)
        
        if not is_relevant:
            # Save to unused links
            self.save_unused_link(url, category, publisher, relevance_info)
            
            return {
                "status": "irrelevant",
                "title": title,
                "reason": relevance_info,
                "url": url,
                "publisher": publisher,
                "identified_publisher": identified_publisher
            }
            
        # Define strict character limit for summary (2-3 lines)
        strict_max_char_limit = 200
            
        # Use newspaper3k's summary if available, otherwise generate our own
        try:
            # Create article with configuration
            config = Config()
            config.browser_user_agent = UserAgent().random
            config.request_timeout = 15
            
            article = Article(url, config=config)
            article.download()
            article.parse()
            article.nlp()  # Extract keywords, summary, etc.
            
            # Use newspaper3k summary if available, but ensure it's very short
            if hasattr(article, 'summary') and article.summary and len(article.summary) > 50:
                # Truncate to ensure it's only 2-3 lines
                if len(article.summary) > strict_max_char_limit:
                    summary = article.summary[:strict_max_char_limit] + "..."
                else:
                    summary = article.summary
            else:
                # Fallback to our simple summarization (first paragraph)
                summary = self.summarize_article(text)
                
            # Get metadata
            metadata = {
                "authors": article.authors,
                "publish_date": article.publish_date.isoformat() if article.publish_date else None,
                "top_image": article.top_image,
                "keywords": article.keywords if hasattr(article, 'keywords') else []
            }
            
        except Exception as e:
            logger.warning(f"Error using newspaper3k for summary: {str(e)}. Using fallback.")
            # Fallback if newspaper3k processing fails
            summary = self.summarize_article(text)
            metadata = {}
        
        return {
            "status": "success",
            "title": title,
            "summary": summary,
            "full_text": text,
            "matched_tags": relevance_info if isinstance(relevance_info, list) else None,
            "url": url,
            "publisher": publisher,
            "identified_publisher": identified_publisher,
            "metadata": metadata  # Include the newspaper3k metadata
        }

# Standalone function for app.py to use
def scrape_and_check_article(url, category=None, publisher=None):
    """
    Function for external use to process an article using newspaper3k
    
    Args:
        url (str): The URL of the article to process
        category (str, optional): The category of the article
        publisher (str, optional): The publisher of the article
        
    Returns:
        dict: The processed article with status, title, summary, etc.
    """
    processor = ArticleProcessor()
    return processor.process_article(url, category, publisher) 