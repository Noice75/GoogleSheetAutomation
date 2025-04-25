import requests
from newspaper import Article, Config
from bs4 import BeautifulSoup
from fake_useragent import UserAgent
import json
import os
import logging
from datetime import datetime
import nltk
import string
import networkx as nx
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.corpus import stopwords
from nltk.cluster.util import cosine_distance
import numpy as np
from urllib.parse import urlparse
import re

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Download necessary NLTK data
try:
    # Create the NLTK data directory if it doesn't exist
    nltk_data_dir = os.path.join(os.path.expanduser('~'), 'nltk_data')
    if not os.path.exists(nltk_data_dir):
        os.makedirs(nltk_data_dir)
    
    # Download all required resources with explicit paths
    nltk.download('punkt', quiet=True, download_dir=nltk_data_dir)
    nltk.download('stopwords', quiet=True, download_dir=nltk_data_dir)
    
    # Also download punkt_tab specifically which is needed for TextRank
    try:
        nltk.download('punkt_tab', quiet=True, download_dir=nltk_data_dir)
    except Exception as e:
        logger.warning(f"Error downloading punkt_tab: {str(e)}. Will use fallback tokenizer.")
    
    # Make sure nltk.tokenize.punkt is properly initialized
    import nltk.data
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        logger.warning("Re-downloading punkt due to lookup error")
        nltk.download('punkt', quiet=False, download_dir=nltk_data_dir)
    
    logger.info("Successfully downloaded NLTK resources")
except Exception as e:
    logger.warning(f"Error downloading NLTK data: {str(e)}")

def manual_sentence_tokenize(text):
    """
    A simple fallback sentence tokenizer when NLTK's sentence tokenizer is not available.
    This is a very basic implementation and doesn't handle all edge cases.
    """
    # Replace common abbreviations to avoid splitting them
    text = text.replace("Mr.", "Mr_DOT_")
    text = text.replace("Mrs.", "Mrs_DOT_")
    text = text.replace("Dr.", "Dr_DOT_")
    text = text.replace("Ph.D.", "PhD_DOT_")
    text = text.replace("i.e.", "ie_DOT_")
    text = text.replace("e.g.", "eg_DOT_")
    
    # Split on sentence-ending punctuation followed by space and uppercase letter
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    
    # Restore the abbreviations
    result = []
    for sentence in sentences:
        sentence = sentence.replace("Mr_DOT_", "Mr.")
        sentence = sentence.replace("Mrs_DOT_", "Mrs.")
        sentence = sentence.replace("Dr_DOT_", "Dr.")
        sentence = sentence.replace("PhD_DOT_", "Ph.D.")
        sentence = sentence.replace("ie_DOT_", "i.e.")
        sentence = sentence.replace("eg_DOT_", "e.g.")
        result.append(sentence)
    
    return result

def safe_sent_tokenize(text):
    """
    A safe wrapper around sent_tokenize that falls back to manual tokenization
    if NLTK's tokenizer encounters an error.
    """
    try:
        sentences = sent_tokenize(text)
        # If we got meaningful sentences, return them
        if len(sentences) > 1:
            return sentences
    except Exception as e:
        logger.warning(f"NLTK sent_tokenize failed: {str(e)}")
    
    # Fallback to manual tokenization
    return manual_sentence_tokenize(text)

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
    
    def _sentence_similarity(self, sent1, sent2, stopwords=None):
        """Calculate similarity between two sentences using word vectors"""
        if stopwords is None:
            try:
                stopwords = set(stopwords.words('english'))
            except:
                stopwords = set()
        
        sent1 = [w.lower() for w in word_tokenize(sent1) if w.lower() not in stopwords and w not in string.punctuation]
        sent2 = [w.lower() for w in word_tokenize(sent2) if w.lower() not in stopwords and w not in string.punctuation]
        
        # If both sentences are empty, they are identical
        if len(sent1) == 0 and len(sent2) == 0:
            return 1.0
        
        # If one is empty and the other isn't, they are completely different
        if len(sent1) == 0 or len(sent2) == 0:
            return 0.0
            
        # Create vocabulary and vectors for both sentences
        all_words = list(set(sent1 + sent2))
        vector1 = [0] * len(all_words)
        vector2 = [0] * len(all_words)
        
        # Build the vectors
        for w in sent1:
            if w in all_words:
                vector1[all_words.index(w)] += 1
                
        for w in sent2:
            if w in all_words:
                vector2[all_words.index(w)] += 1
                
        # Calculate cosine similarity
        return 1 - cosine_distance(vector1, vector2)
    
    def _build_similarity_matrix(self, sentences, stopwords=None):
        """Build similarity matrix for all sentences"""
        # Create an empty similarity matrix
        similarity_matrix = np.zeros((len(sentences), len(sentences)))
        
        for i in range(len(sentences)):
            for j in range(len(sentences)):
                if i != j:
                    similarity_matrix[i][j] = self._sentence_similarity(sentences[i], sentences[j], stopwords)
                    
        return similarity_matrix
    
    def summarize_article(self, text, max_sentences=2, fallback_max_length=150):
        """
        Create a very concise summary that attracts readers - just 2-3 lines maximum.
        Focuses on the key points rather than details.
        
        First tries using newspaper3k's built-in summarization if we have a URL,
        then falls back to TextRank if that fails.
        """
        if not text:
            return ""
        
        # Define stricter character limits for a shorter, more attractive summary
        # 200 chars is approximately 2-3 lines
        strict_max_char_limit = 200
        
        # TextRank summarization
        try:
            # Get stopwords
            try:
                stop_words = set(stopwords.words('english'))
            except Exception as e:
                logger.warning(f"Error loading stopwords: {str(e)}")
                stop_words = set()
            
            # Tokenize the text into sentences using our safe wrapper
            sentences = safe_sent_tokenize(text)
                
            # If no sentences found or too few, fallback to truncation
            if not sentences or len(sentences) <= 1:
                logger.warning("Could not extract sentences from text, using truncation")
                # Much shorter summary for newsletter format
                return text[:strict_max_char_limit] + "..." if len(text) > strict_max_char_limit else text
                    
            # If there are very few sentences, just return them all or truncate them
            if len(sentences) <= max_sentences:
                combined = ' '.join(sentences)
                if len(combined) > strict_max_char_limit:
                    # Truncate to strict limit and add ellipsis
                    return combined[:strict_max_char_limit] + "..."
                return combined
            
            # Extract key sentences focusing on the beginning of the article
            # which typically contains the main point/topic
            intro_weight = 2.5  # Give more weight to introductory sentences for a "hook"
            
            # Build similarity matrix
            sentence_similarity_matrix = self._build_similarity_matrix(sentences, stop_words)
            
            # Rank sentences using PageRank algorithm with bias toward early sentences
            nx_graph = nx.from_numpy_array(sentence_similarity_matrix)
            
            # Add bias for early sentences (first 15% of the article)
            # More focused on the very beginning for a hook
            initial_sentences = max(1, int(len(sentences) * 0.15))
            personalization = {}
            for i in range(len(sentences)):
                if i < initial_sentences:
                    personalization[i] = intro_weight
                else:
                    personalization[i] = 1.0
            
            # Apply PageRank with personalization to favor early sentences
            scores = nx.pagerank(nx_graph, personalization=personalization)
            
            # Sort sentences by score and select top ones
            ranked_sentences = sorted(((scores[i], i, s) for i, s in enumerate(sentences)), reverse=True)
            
            # Get the top N sentences (limited to just 1-2 for brevity)
            max_sentences = min(max_sentences, 2)  # Limit to 1-2 sentences max
            top_sentence_indices = [ranked_sentences[i][1] for i in range(min(max_sentences, len(ranked_sentences)))]
            
            # Sort the selected sentences by their position in the original text
            # to maintain logical flow
            top_sentence_indices.sort()
            
            # Join the selected sentences
            summary = ' '.join([sentences[i] for i in top_sentence_indices])
            
            # Always enforce the strict character limit
            if len(summary) > strict_max_char_limit:
                return summary[:strict_max_char_limit] + "..."
                
            return summary
            
        except Exception as e:
            logger.warning(f"Error in article summarization: {str(e)}. Falling back to simple truncation.")
            # Fallback to simple truncation if summarization fails
            # Keep it very short
            if len(text) > strict_max_char_limit:
                return text[:strict_max_char_limit] + "..."
            return text
    
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
                # Fallback to our custom summarization which is already configured for brevity
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