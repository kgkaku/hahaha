#!/usr/bin/env python3
"""
Aparatchi.com M3U Generator - Fixed version
"""

import subprocess
import sys
import os

# First, install basic requirements without needing config
def install_basic_requirements():
    """Install minimal requirements first"""
    basic_reqs = ['pyyaml', 'requests', 'beautifulsoup4', 'lxml']
    
    for req in basic_reqs:
        try:
            __import__(req.replace('-', '_'))
            print(f"✅ {req} already installed")
        except ImportError:
            print(f"📦 Installing {req}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", req])

# Install basic requirements first
install_basic_requirements()

# Now we can safely import
import re
import json
import requests
import yaml
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from datetime import datetime
import argparse

class AparatchiScraper:
    def __init__(self, config_file='config.yml', debug=False, session_id=None):
        self.debug = debug
        self.config = self._load_config(config_file)
        self.base_url = self.config.get('website', {}).get('url', 'https://www.aparatchi.com')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.config.get('output', {}).get('user_agent', 
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        })
        self.channels = []
        self.session_id = session_id
        self.filters = self.config.get('filters', {})

    def _load_config(self, config_file):
        """Safely load config with defaults"""
        default_config = {
            'website': {'url': 'https://www.aparatchi.com', 'timeout': 10},
            'stream': {
                'domains': ['gg.hls2.xyz'],
                'path_patterns': ['/live/{channel_id}/chunks.m3u8'],
                'session_param': 'nimblesessionid'
            },
            'output': {
                'm3u': 'aparatchi.m3u',
                'json': 'aparatchi.json',
                'include_headers': True,
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            },
            'filters': {
                'min_name_length': 2,
                'max_name_length': 30,
                'exclude_patterns': ['login', 'register', 'contact', 'about']
            }
        }
        
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    user_config = yaml.safe_load(f)
                    # Merge configs
                    if user_config:
                        for key, value in user_config.items():
                            if key in default_config and isinstance(value, dict):
                                default_config[key].update(value)
                            else:
                                default_config[key] = value
        except Exception as e:
            print(f"⚠️  Could not load config file: {e}")
            print("   Using default configuration")
        
        return default_config

    def log(self, msg, level="info"):
        if self.debug:
            prefix = {
                "info": "ℹ️",
                "success": "✅",
                "error": "❌",
                "warning": "⚠️"
            }.get(level, "ℹ️")
            print(f"{prefix} {msg}")

    def scrape(self):
        print("🔄 Fetching main page...")
        try:
            response = self.session.get(
                self.base_url, 
                timeout=self.config['website'].get('timeout', 10)
            )
            html = response.text
        except Exception as e:
            print(f"❌ Failed to fetch page: {e}")
            return []

        # Extract session ID if not provided manually
        if not self.session_id:
            self.session_id = self._extract_session_id(html)
        
        if self.session_id:
            print(f"✅ Session ID: {self.session_id}")
        else:
            print("⚠️  No session ID found - streams may not work")
        
        # Parse channels
        soup = BeautifulSoup(html, 'lxml')
        
        # Look for channel links
        all_links = soup.find_all('a', href=True)
        
        for link in all_links:
            channel = self._parse_channel(link)
            if channel and self._should_include(channel):
                self._add_channel(channel)
        
        # Generate stream URLs
        print(f"📡 Generating stream URLs for {len(self.channels)} channels...")
        for channel in self.channels:
            self._generate_stream_url(channel)
        
        print(f"✅ Found {len(self.channels)} channels")
        return self.channels

    def _extract_session_id(self, html):
        """Try multiple patterns to find session ID"""
        patterns = [
            r'nimblesessionid=(\d+)',
            r'session[_-]id["\']?\s*[:=]\s*["\']?(\d+)["\']?',
            r'live[\/\\][^\/]+[\/\\]chunks\.m3u8\?nimblesessionid=(\d+)',
            r'[?&]nimblesessionid=(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Try to find in script tags
        script_pattern = r'<script[^>]*>([^<]*nimblesessionid[^<]*)</script>'
        scripts = re.findall(script_pattern, html, re.IGNORECASE | re.DOTALL)
        for script in scripts:
            id_match = re.search(r'nimblesessionid["\']?\s*[:=]\s*["\']?(\d+)["\']?', script)
            if id_match:
                return id_match.group(1)
        
        return None

    def _parse_channel(self, link):
        """Extract channel info from a link"""
        href = link.get('href', '')
        name = link.get_text(strip=True)
        
        if not name or not href or len(name) > 50:
            return None
        
        # Clean up name
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Skip obvious non-channels
        skip_words = ['login', 'register', 'contact', 'about', 'home', 'terms', 
                     'privacy', 'dmca', 'cookie', 'policy', 'facebook', 'twitter',
                     'instagram', 'telegram', 'whatsapp', 'youtube']
        if any(skip in name.lower() for skip in skip_words):
            return None
        
        # Extract logo
        logo = None
        img = link.find('img')
        if img:
            logo = img.get('src') or img.get('data-src') or img.get('data-original')
            if logo:
                if logo.startswith('//'):
                    logo = 'https:' + logo
                elif logo.startswith('/'):
                    logo = urljoin(self.base_url, logo)
        
        # Generate tvg-id
        tvg_id = re.sub(r'[^\w\s-]', '', name)
        tvg_id = re.sub(r'[-\s]+', '.', tvg_id).lower()
        
        return {
            'name': name,
            'url': urljoin(self.base_url, href),
            'category': 'Uncategorized',
            'logo': logo,
            'tvg_id': tvg_id,
            'tvg_name': name,
            'tvg_logo': logo,
            'stream_url': None
        }

    def _should_include(self, channel):
        """Apply filters to determine if channel should be included"""
        name = channel['name']
        
        # Length filters
        min_len = self.filters.get('min_name_length', 2)
        max_len = self.filters.get('max_name_length', 30)
        
        if len(name) < min_len or len(name) > max_len:
            return False
        
        # Exclude patterns
        exclude = self.filters.get('exclude_patterns', [])
        for pattern in exclude:
            if pattern.lower() in name.lower():
                return False
        
        return True

    def _add_channel(self, channel):
        """Add channel if not duplicate"""
        for existing in self.channels:
            if existing['name'].lower() == channel['name'].lower():
                return
        self.channels.append(channel)

    def _generate_stream_url(self, channel):
        """Generate stream URL using patterns from config"""
        channel_id = channel['tvg_id']
        channel_name = channel['name'].lower().replace(' ', '').replace('.', '')
        
        stream_config = self.config.get('stream', {})
        domains = stream_config.get('domains', ['gg.hls2.xyz'])
        patterns = stream_config.get('path_patterns', ['/live/{channel_id}/chunks.m3u8'])
        session_param = stream_config.get('session_param', 'nimblesessionid')
        
        for domain in domains:
            for pattern in patterns:
                try:
                    path = pattern.format(
                        channel_id=channel_id,
                        channel_name=channel_name
                    )
                    url = f"https://{domain}{path}"
                    
                    if self.session_id:
                        url += f"?{session_param}={self.session_id}"
                    
                    channel['stream_url'] = url
                    return True
                except:
                    continue
        
        return False

    def save_m3u(self, filename=None):
        """Save channels to M3U file"""
        filename = filename or self.config['output'].get('m3u', 'aparatchi.m3u')
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            f.write(f"#PLAYLIST: Aparatchi.com Channels\n")
            f.write(f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            if self.session_id:
                f.write(f"# Session ID: {self.session_id}\n")
            f.write(f"# Channels: {len(self.channels)}\n\n")
            
            valid_channels = [ch for ch in self.channels if ch.get('stream_url')]
            
            for ch in valid_channels:
                # EXTINF line with attributes
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
        
        print(f"✅ Saved M3U: {filename} with {len(valid_channels)} channels")

    def save_json(self, filename=None):
        """Save channels to JSON file"""
        filename = filename or self.config['output'].get('json', 'aparatchi.json')
        
        data = {
            'generated': datetime.now().isoformat(),
            'session_id': self.session_id,
            'total_channels': len(self.channels),
            'channels': self.channels
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Saved JSON: {filename}")

def main():
    parser = argparse.ArgumentParser(description='Aparatchi.com M3U Generator')
    parser.add_argument('--config', '-c', default='config.yml', help='Config file path')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug output')
    parser.add_argument('--session-id', '-s', help='Manually provide session ID')
    parser.add_argument('--output-m3u', '-o', help='Output M3U filename')
    parser.add_argument('--output-json', '-j', help='Output JSON filename')
    
    args = parser.parse_args()
    
    print("╔════════════════════════════════════╗")
    print("║   Aparatchi M3U Generator v2.1    ║")
    print("╚════════════════════════════════════╝")
    
    scraper = AparatchiScraper(
        config_file=args.config,
        debug=args.debug,
        session_id=args.session_id
    )
    
    try:
        channels = scraper.scrape()
        
        if channels:
            scraper.save_m3u(args.output_m3u)
            scraper.save_json(args.output_json)
            print(f"\n✨ Done! Generated {len(channels)} channels")
        else:
            print("❌ No channels found")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
