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
import tempfile
import random

# Get logger
logger = logging.getLogger(__name__)

# Ensure newspaper temp directory exists
newspaper_dir = os.path.join(tempfile.gettempdir(), '.newspaper_scraper')
article_resources_dir = os.path.join(newspaper_dir, 'article_resources')
os.makedirs(article_resources_dir, exist_ok=True)
logger.info(f"Ensured newspaper temp directory exists: {article_resources_dir}")

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
    
    def _get_summary_style(self):
        """
        Returns a randomly selected summary style approach to create
        more natural-sounding summaries with variety in structure.
        """
        styles = [
            # No explicit attribution phrases
            {"prefix": "", "mid_text": "", "probability": 0.3},
            
            # Prefix attribution phrases
            {"prefix": "The article covers ", "mid_text": "", "probability": 0.1},
            {"prefix": "A look at ", "mid_text": "", "probability": 0.1},
            {"prefix": "An exploration of ", "mid_text": "", "probability": 0.05},
            
            # Mid-text attribution phrases
            {"prefix": "", "mid_text": ", according to this article", "probability": 0.1},
            {"prefix": "", "mid_text": ", as explained in the piece", "probability": 0.1},
            {"prefix": "", "mid_text": ", the article highlights", "probability": 0.1},
            {"prefix": "", "mid_text": ", the report suggests", "probability": 0.05},
            
            # Combined approach
            {"prefix": "In this analysis of ", "mid_text": ", the author argues that", "probability": 0.05},
            {"prefix": "The piece discusses ", "mid_text": " and emphasizes", "probability": 0.05}
        ]
        
        # Use weighted random selection based on probability
        total_prob = sum(style["probability"] for style in styles)
        rand_val = random.random() * total_prob
        
        cumulative_prob = 0
        for style in styles:
            cumulative_prob += style["probability"]
            if rand_val <= cumulative_prob:
                return style
                
        # Fallback
        return {"prefix": "", "mid_text": "", "probability": 1.0}
    
    def summarize_article(self, text, max_length=300):
        """
        Create a natural-sounding summary with variety in structure and phrasing.
        """
        if not text:
            return ""
        
        # Extract first paragraph and other content for context
        first_para = text.split('\n\n')[0]
        
        # Get a summary style with natural-sounding phrasing
        style = self._get_summary_style()
        prefix = style["prefix"]
        mid_text = style["mid_text"]
        
        # Extract key sentences using regex
        sentences = re.findall(r'[^.!?]*[.!?](?:\s|$)', text[:800])  # Look at more text for better context
        
        if not sentences:
            # Fallback to simple approach
            if len(first_para) <= max_length - len(prefix):
                return prefix + first_para.strip()
            
            # Try to end at the last complete sentence
            cut_text = first_para[:max_length - len(prefix)]
            last_period = cut_text.rfind('.')
            last_question = cut_text.rfind('?')
            last_exclamation = cut_text.rfind('!')
            
            # Find the last sentence ending punctuation
            last_end = max(last_period, last_question, last_exclamation)
            
            if last_end > 0:
                return prefix + first_para[:last_end + 1].strip()
            
            # If no sentence ending found, try to cut at the last space
            last_space = cut_text.rfind(' ')
            if last_space > (max_length - len(prefix)) * 0.8:
                cut_text = cut_text[:last_space]
                
            return prefix + cut_text.strip()
        
        # If we have mid_text, we need to find a good place to insert it
        if mid_text:
            # We'll need at least 2 sentences for mid-text insertion
            if len(sentences) >= 2:
                first_sentence = sentences[0].strip()
                remaining_sentences = sentences[1:]
                
                # Build summary with mid-text inserted after first sentence
                summary = prefix + first_sentence + mid_text + " "
                content_length = len(summary)
                
                # Add complete sentences until we approach max length
                for sentence in remaining_sentences:
                    sentence_clean = sentence.strip()
                    if not sentence_clean:
                        continue
                    
                    # Only add complete sentences that fit within the limit
                    if content_length + len(sentence_clean) <= max_length:
                        summary += sentence_clean + " "
                        content_length += len(sentence_clean) + 1
                    else:
                        break
                
                return summary.strip()
            else:
                # Not enough sentences for mid-text, fallback to prefix only
                mid_text = ""
        
        # Standard summary construction with prefix only
        summary = prefix
        content_length = len(summary)
        
        # Add complete sentences until we approach the max length
        for sentence in sentences:
            sentence_clean = sentence.strip()
            if not sentence_clean:
                continue
                
            # Only add complete sentences that fit within the limit
            if content_length + len(sentence_clean) <= max_length:
                summary += sentence_clean + " "
                content_length += len(sentence_clean) + 1
            else:
                break
                
        return summary.strip()
    
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
            
        # Define character limit for summary 
        strict_max_char_limit = 300  # Set to 300 characters as requested
            
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
            
            # Generate a natural-sounding summary
            if hasattr(article, 'summary') and article.summary and len(article.summary) > 50:
                # Use our summarize_article method with the newspaper3k summary as input
                # This ensures consistent style with variety in phrasing
                summary = self.summarize_article(article.summary, strict_max_char_limit)
            else:
                # Fallback to our summarization on the full text
                summary = self.summarize_article(text, strict_max_char_limit)
                
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
            summary = self.summarize_article(text, strict_max_char_limit)
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