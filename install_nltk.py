#!/usr/bin/env python
"""
Utility script to download NLTK resources needed for the application.
Run this script separately if you encounter NLTK resource errors.
"""

import os
import sys
import nltk
import time

def download_nltk_resources():
    """Download all required NLTK resources"""
    # Create nltk_data directory in user's home folder
    nltk_data_dir = os.path.join(os.path.expanduser('~'), 'nltk_data')
    if not os.path.exists(nltk_data_dir):
        print(f"Creating NLTK data directory at {nltk_data_dir}")
        os.makedirs(nltk_data_dir)
    else:
        print(f"Using existing NLTK data directory at {nltk_data_dir}")
    
    # List of resources to download
    resources = ['punkt', 'stopwords']
    
    # Download each resource
    for resource in resources:
        print(f"Downloading NLTK resource: {resource}...")
        try:
            nltk.download(resource, download_dir=nltk_data_dir, quiet=False)
            # Check if the resource can be found
            nltk.data.find(f'tokenizers/{resource}' if resource == 'punkt' else f'corpora/{resource}')
            print(f"✓ Successfully downloaded and verified {resource}")
        except Exception as e:
            print(f"⚠ Error downloading {resource}: {str(e)}")
            
    # Make sure we properly initialize the punkt tokenizer
    try:
        from nltk.tokenize import sent_tokenize
        text = "This is a test sentence. Here is another one."
        sentences = sent_tokenize(text)
        print(f"\nTesting sentence tokenization...")
        for sentence in sentences:
            print(f"  - {sentence}")
        print("\nSentence tokenization working correctly.")
    except Exception as e:
        print(f"\n✗ Error testing sentence tokenization: {str(e)}")
        print("Try manually running: nltk.download('punkt')")
    
    # Test the manual fallback tokenizer just in case
    print("\nTesting manual fallback tokenizer...")
    text = "This is a test sentence. Here is another one. Mr. Smith visited Dr. Johnson."
    try:
        # Define a simple manual tokenizer for testing
        import re
        def manual_tokenize(text):
            text = text.replace("Mr.", "Mr_DOT_").replace("Dr.", "Dr_DOT_")
            sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
            sentences = [s.replace("Mr_DOT_", "Mr.").replace("Dr_DOT_", "Dr.") for s in sentences]
            return sentences
            
        sentences = manual_tokenize(text)
        for sentence in sentences:
            print(f"  - {sentence}")
        print("Manual tokenization working correctly as fallback.")
    except Exception as e:
        print(f"Error testing manual tokenization: {str(e)}")
        
    print("\nNLTK resource installation completed.")

if __name__ == "__main__":
    print("==== NLTK Resource Installer ====")
    print("This script will download the necessary NLTK resources for the application.")
    print("Please wait while the resources are being downloaded...\n")
    
    try:
        download_nltk_resources()
        print("\nAll done! You can now run the application.")
        time.sleep(1)  # Give user time to read the message
    except Exception as e:
        print(f"\nAn unexpected error occurred: {str(e)}")
        print("Please try running the script again or manually install the NLTK resources.")
        sys.exit(1) 