#!/usr/bin/env python3
"""
Aparatchi.com M3U Generator - Single file script
"""

import subprocess
import sys

def check_requirements(config_file='config.yml'):
    """Check and install requirements from config"""
    with open(config_file, 'r') as f:
        import yaml
        config = yaml.safe_load(f)
    
    requirements = config.get('requirements', [])
    for req in requirements:
        try:
            __import__(req.split('>=')[0].split('=')[0])
        except ImportError:
            print(f"Installing {req}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", req])

# Check requirements first
check_requirements()

# Now import everything
import re
import json
import requests
import yaml
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime

class AparatchiScraper:
    def __init__(self, config_file='config.yml'):
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.base_url = self.config['website']['url']
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.config['output']['user_agent']
        })
        self.channels = []
        self.session_id = None
        self.filters = self.config.get('filters', {})

    def scrape(self):
        print("🔄 Fetching main page...")
        html = self.session.get(self.base_url).text
        
        # Extract session ID
        session_match = re.search(r'nimblesessionid=(\d+)', html)
        self.session_id = session_match.group(1) if session_match else None
        print(f"✅ Session ID: {self.session_id}")
        
        # Parse channels
        soup = BeautifulSoup(html, 'lxml')
        for link in soup.find_all('a', href=True):
            name = link.get_text(strip=True)
            
            # Apply filters
            if not self._should_include(name, link['href']):
                continue
            
            channel = {
                'name': name,
                'url': urljoin(self.base_url, link['href']),
                'logo': self._extract_logo(link),
                'tvg_id': re.sub(r'\s+', '.', name.lower()),
                'stream_url': None
            }
            
            if channel not in self.channels:
                self.channels.append(channel)
        
        # Generate stream URLs
        for channel in self.channels:
            self._generate_stream_url(channel)
        
        print(f"✅ Found {len(self.channels)} channels")
        return self.channels

    def _should_include(self, name, url):
        """Apply filters to channel names"""
        if not name:
            return False
        
        min_len = self.filters.get('min_name_length', 2)
        max_len = self.filters.get('max_name_length', 30)
        
        if len(name) < min_len or len(name) > max_len:
            return False
        
        exclude_patterns = self.filters.get('exclude_patterns', [])
        for pattern in exclude_patterns:
            if pattern.lower() in name.lower() or pattern.lower() in url.lower():
                return False
        
        return True

    def _extract_logo(self, link):
        img = link.find('img')
        if img:
            return urljoin(self.base_url, img.get('src') or img.get('data-src', ''))
        return None

    def _generate_stream_url(self, channel):
        """Generate stream URL using patterns from config"""
        channel_id = channel['tvg_id']
        channel_name = channel['name'].lower().replace(' ', '')
        
        for domain in self.config['stream']['domains']:
            for pattern in self.config['stream']['path_patterns']:
                path = pattern.format(
                    channel_id=channel_id,
                    channel_name=channel_name
                )
                url = f"https://{domain}{path}"
                
                if self.session_id:
                    url += f"?{self.config['stream']['session_param']}={self.session_id}"
                
                # Quick test (optional)
                # if self._test_url(url):
                channel['stream_url'] = url
                return True
        return False

    def _test_url(self, url):
        """Quickly test if URL is accessible"""
        try:
            response = self.session.head(url, timeout=2)
            return response.status_code < 400
        except:
            return False

    def save_m3u(self, filename=None):
        filename = filename or self.config['output']['m3u']
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            f.write(f"# Updated: {datetime.now()}\n")
            f.write(f"# Session ID: {self.session_id}\n")
            f.write(f"# Channels: {len(self.channels)}\n\n")
            
            for ch in self.channels:
                if ch.get('stream_url'):
                    # EXTINF line
                    extinf = f'#EXTINF:-1'
                    if ch['tvg_id']:
                        extinf += f' tvg-id="{ch["tvg_id"]}"'
                    if ch.get('logo'):
                        extinf += f' tvg-logo="{ch["logo"]}"'
                    extinf += f',{ch["name"]}\n'
                    f.write(extinf)
                    
                    # Headers (if enabled)
                    if self.config['output'].get('include_headers', True):
                        f.write(f'#EXTVLCOPT:http-referrer={self.base_url}/\n')
                        f.write(f'#EXTVLCOPT:http-user-agent={self.config["output"]["user_agent"]}\n')
                    
                    # Stream URL
                    f.write(f'{ch["stream_url"]}\n\n')
        
        print(f"✅ Saved {filename}")

    def save_json(self, filename=None):
        filename = filename or self.config['output']['json']
        
        data = {
            'generated': str(datetime.now()),
            'session_id': self.session_id,
            'total_channels': len(self.channels),
            'config': self.config,
            'channels': self.channels
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Saved {filename}")

if __name__ == "__main__":
    scraper = AparatchiScraper()
    scraper.scrape()
    scraper.save_m3u()
    scraper.save_json()
