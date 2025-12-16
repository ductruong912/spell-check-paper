"""
Google Search-based Plagiarism Checker
Uses Google Custom Search API to detect plagiarism for FREE (100 searches/day)

Setup:
1. Get Google API Key: https://console.cloud.google.com/apis/credentials
2. Create Custom Search Engine: https://programmablesearchengine.google.com/
3. Add to .env file:
   GOOGLE_API_KEY=your_api_key
   GOOGLE_SEARCH_ENGINE_ID=your_engine_id
"""

import os
import re
import json
import time
import hashlib
from typing import List, Dict, Tuple, Optional
from urllib.parse import quote_plus
import requests


class GooglePlagiarismChecker:
    """Free plagiarism checker using Google Custom Search API."""
    
    def __init__(self, api_key: str, search_engine_id: str):
        """
        Initialize checker with Google API credentials.
        
        Args:
            api_key: Google API key
            search_engine_id: Custom Search Engine ID
        """
        self.api_key = api_key
        self.search_engine_id = search_engine_id
        self.base_url = "https://www.googleapis.com/customsearch/v1"
        
    def extract_sentences(self, text: str, min_words: int = 15) -> List[str]:
        """
        Extract meaningful sentences from text.
        
        Args:
            text: Input text
            min_words: Minimum words per sentence
            
        Returns:
            List of sentences
        """
        # Split by sentence endings
        sentences = re.split(r'[.!?]+\s+', text)
        
        # Filter out short sentences and clean up
        meaningful = []
        for sent in sentences:
            sent = sent.strip()
            word_count = len(sent.split())
            
            # Keep sentences with enough words
            if word_count >= min_words and len(sent) >= 80:
                # Remove citations like [1], (2020), etc.
                cleaned = re.sub(r'\[\d+\]', '', sent)
                cleaned = re.sub(r'\(\d{4}\)', '', cleaned)
                cleaned = re.sub(r'\s+', ' ', cleaned).strip()
                
                if len(cleaned) >= 80:
                    meaningful.append(cleaned)
        
        return meaningful
    
    def create_search_queries(self, text: str, max_queries: int = 10) -> List[str]:
        """
        Create search queries from text by extracting key phrases.
        
        Args:
            text: Input text
            max_queries: Maximum number of queries to create
            
        Returns:
            List of search query strings
        """
        sentences = self.extract_sentences(text, min_words=15)
        
        # Take diverse samples
        queries = []
        
        if len(sentences) <= max_queries:
            queries = sentences[:max_queries]
        else:
            # Take from beginning, middle, and end
            step = len(sentences) // max_queries
            for i in range(0, len(sentences), step):
                if len(queries) >= max_queries:
                    break
                queries.append(sentences[i])
        
        return queries[:max_queries]
    
    def search_google(self, query: str) -> Dict:
        """
        Search Google using Custom Search API.
        
        Args:
            query: Search query string
            
        Returns:
            API response dict
        """
        # Truncate query if too long (Google has 2048 char limit)
        if len(query) > 200:
            query = query[:200]
        
        params = {
            'key': self.api_key,
            'cx': self.search_engine_id,
            'q': query,
            'num': 5  # Number of results
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    'error': f'API Error: {response.status_code}',
                    'message': response.text
                }
        except Exception as e:
            return {
                'error': 'Request failed',
                'message': str(e)
            }
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate simple similarity between two texts.
        
        Args:
            text1: First text
            text2: Second text
            
        Returns:
            Similarity score (0-100)
        """
        # Normalize texts
        t1 = re.sub(r'[^\w\s]', '', text1.lower())
        t2 = re.sub(r'[^\w\s]', '', text2.lower())
        
        words1 = set(t1.split())
        words2 = set(t2.split())
        
        if not words1 or not words2:
            return 0.0
        
        # Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return (intersection / union) * 100 if union > 0 else 0.0
    
    def check_plagiarism(
        self, 
        text: str, 
        max_queries: int = 10,
        delay: float = 1.0,
        progress_callback=None
    ) -> Dict:
        """
        Check plagiarism by searching text on Google.
        
        Args:
            text: Text to check
            max_queries: Maximum number of Google searches
            delay: Delay between searches (seconds)
            progress_callback: Optional callback function(current, total, message)
            
        Returns:
            Dict with plagiarism results
        """
        # Create search queries
        queries = self.create_search_queries(text, max_queries=max_queries)
        
        if not queries:
            return {
                'success': False,
                'error': 'No valid search queries could be created from text'
            }
        
        # Search each query
        total_queries = len(queries)
        sources_found = []
        queries_with_results = 0
        
        for idx, query in enumerate(queries, 1):
            if progress_callback:
                progress_callback(idx, total_queries, f"Searching query {idx}/{total_queries}...")
            
            result = self.search_google(query)
            
            if 'error' in result:
                continue
            
            # Process search results
            items = result.get('items', [])
            
            if items:
                queries_with_results += 1
                
                for item in items:
                    title = item.get('title', '')
                    url = item.get('link', '')
                    snippet = item.get('snippet', '')
                    
                    # Calculate similarity
                    similarity = self.calculate_similarity(query, snippet)
                    
                    if similarity > 30:  # Threshold for considering it a match
                        sources_found.append({
                            'query': query[:100] + '...' if len(query) > 100 else query,
                            'title': title,
                            'url': url,
                            'snippet': snippet,
                            'similarity': round(similarity, 2)
                        })
            
            # Delay to respect API rate limits
            if idx < total_queries:
                time.sleep(delay)
        
        # Calculate plagiarism score
        plagiarism_score = 0
        if total_queries > 0:
            plagiarism_score = (queries_with_results / total_queries) * 100
        
        # Remove duplicates (same URL)
        unique_sources = {}
        for source in sources_found:
            url = source['url']
            if url not in unique_sources or source['similarity'] > unique_sources[url]['similarity']:
                unique_sources[url] = source
        
        sources_list = sorted(
            unique_sources.values(), 
            key=lambda x: x['similarity'], 
            reverse=True
        )
        
        return {
            'success': True,
            'plagiarism_score': round(plagiarism_score, 2),
            'queries_checked': total_queries,
            'queries_with_matches': queries_with_results,
            'sources_found': len(sources_list),
            'sources': sources_list[:20],  # Top 20 sources
            'message': f'Checked {total_queries} text samples, found matches in {queries_with_results} searches'
        }


def main():
    """CLI usage example."""
    import argparse
    from pathlib import Path
    from dotenv import load_dotenv
    
    load_dotenv()
    
    parser = argparse.ArgumentParser(description='Check plagiarism using Google Search')
    parser.add_argument('text_file', help='Text file to check')
    parser.add_argument('--queries', type=int, default=10, help='Max number of queries')
    parser.add_argument('--output', help='Output JSON file')
    args = parser.parse_args()
    
    # Get API credentials
    api_key = os.getenv('GOOGLE_API_KEY')
    search_engine_id = os.getenv('GOOGLE_SEARCH_ENGINE_ID')
    
    if not api_key or not search_engine_id:
        print("ERROR: Missing API credentials!")
        print("Please set in .env file:")
        print("  GOOGLE_API_KEY=your_api_key")
        print("  GOOGLE_SEARCH_ENGINE_ID=your_engine_id")
        print("\nGet API key: https://console.cloud.google.com/apis/credentials")
        print("Create search engine: https://programmablesearchengine.google.com/")
        return
    
    # Read text
    text = Path(args.text_file).read_text(encoding='utf-8')
    
    # Check plagiarism
    checker = GooglePlagiarismChecker(api_key, search_engine_id)
    
    def progress(current, total, msg):
        print(f"[{current}/{total}] {msg}")
    
    print(f"Checking plagiarism with max {args.queries} queries...")
    result = checker.check_plagiarism(text, max_queries=args.queries, progress_callback=progress)
    
    # Display results
    print("\n" + "="*60)
    if result['success']:
        print(f"Plagiarism Score: {result['plagiarism_score']}%")
        print(f"Queries Checked: {result['queries_checked']}")
        print(f"Matches Found: {result['queries_with_matches']}")
        print(f"Unique Sources: {result['sources_found']}")
        print("\nTop Sources:")
        for i, source in enumerate(result['sources'][:5], 1):
            print(f"\n{i}. {source['title']}")
            print(f"   URL: {source['url']}")
            print(f"   Similarity: {source['similarity']}%")
    else:
        print(f"ERROR: {result.get('error', 'Unknown error')}")
    
    # Save to file
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"\nResults saved to: {args.output}")


if __name__ == '__main__':
    main()
