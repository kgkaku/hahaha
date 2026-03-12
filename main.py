#!/usr/bin/env python3
"""
Aparatchi.com M3U Generator - Complete working script
"""

import subprocess
import sys
import os
import argparse

def check_requirements(config_file='config.yml'):
    """Check and install requirements from config"""
    try:
        with open(config_file, 'r') as f:
            import yaml
            config = yaml.safe_load(f)
        
        requirements = config.get('requirements', [])
        for req in requirements:
            try:
                __import__(req.split('>=')[0].split('=')[0])
            except ImportError:
                print(f"📦 Installing {req}...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", req])
    except Exception as e:
        print(f"⚠️  Requirements check skipped: {e}")

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
import argparse

class AparatchiScraper:
    def __init__(self, config_file='config.yml', debug=False, session_id=None):
        with open(config_file, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.debug = debug
        self.base_url = self.config['website']['url']
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.config['output']['user_agent']
        })
        self.channels = []
        self.session_id = session_id  # Allow manual session ID
        self.filters = self.config.get('filters', {})

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
            response = self.session.get(self.base_url, timeout=10)
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
        
        # Method 1: Look in category sections
        containers = soup.find_all(['div', 'section', 'ul'], 
                                  class_=re.compile(r'category|menu|recommend|popular|grid', re.I))
        
        for container in containers:
            category = self._get_category_name(container)
            links = container.find_all('a', href=True)
            
            for link in links:
                channel = self._parse_channel(link, category)
                if channel and self._should_include(channel):
                    self._add_channel(channel)
        
        # Method 2: Look for any channel-like links if we found too few
        if len(self.channels) < 10:
            print("🔍 Using fallback channel detection...")
            all_links = soup.find_all('a', href=True)
            for link in all_links:
                channel = self._parse_channel(link, "Uncategorized")
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
            # Direct nimblesessionid parameter
            r'nimblesessionid=(\d+)',
            r'session[_-]id["\']?\s*[:=]\s*["\']?(\d+)["\']?',
            r'live[\/\\][^\/]+[\/\\]chunks\.m3u8\?nimblesessionid=(\d+)',
            r'[?&]nimblesessionid=(\d+)',
            r'var\s+sessionId\s*=\s*["\']?(\d+)["\']?',
            r'session["\']?\s*:\s*["\']?(\d+)["\']?',
            # Look in script tags
            r'<script[^>]*>([^<]*nimblesessionid[^<]*)</script>',
        ]
        
        for pattern in patterns:
            # For script tag pattern, we need to extract differently
            if pattern.startswith('<script'):
                scripts = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
                for script in scripts:
                    id_match = re.search(r'nimblesessionid["\']?\s*[:=]\s*["\']?(\d+)["\']?', script)
                    if id_match:
                        return id_match.group(1)
            else:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    return match.group(1)
        
        # Try to find in network requests (if we had a headless browser, but we don't)
        return None

    def _get_category_name(self, container):
        """Extract category name from container"""
        # Try headings
        for heading in ['h2', 'h3', 'h4', 'span.title', 'div.title']:
            elem = container.find(heading.split('.')[0], 
                                 class_=heading.split('.')[1] if '.' in heading else None)
            if elem:
                return elem.get_text(strip=True)
        
        # Try data attributes
        if container.get('data-category'):
            return container['data-category']
        
        # Try class name
        if container.get('class'):
            for cls in container['class']:
                if 'category' in cls.lower() or 'menu' in cls.lower():
                    return cls.replace('category-', '').replace('menu-', '').title()
        
        return "Uncategorized"

    def _parse_channel(self, link, category):
        """Extract channel info from a link"""
        href = link.get('href', '')
        name = link.get_text(strip=True)
        
        if not name or not href:
            return None
        
        # Clean up name
        name = re.sub(r'\s+', ' ', name).strip()
        
        # Skip obvious non-channels
        if any(skip in name.lower() for skip in ['login', 'register', 'contact', 'about', 'home']):
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
            'category': category,
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
            if existing['name'] == channel['name']:
                return
        self.channels.append(channel)

    def _generate_stream_url(self, channel):
        """Generate stream URL using patterns from config"""
        channel_id = channel['tvg_id']
        channel_name = channel['name'].lower().replace(' ', '').replace('.', '')
        
        for domain in self.config['stream']['domains']:
            for pattern in self.config['stream']['path_patterns']:
                try:
                    path = pattern.format(
                        channel_id=channel_id,
                        channel_name=channel_name
                    )
                    url = f"https://{domain}{path}"
                    
                    if self.session_id:
                        url += f"?{self.config['stream']['session_param']}={self.session_id}"
                    
                    channel['stream_url'] = url
                    return True
                except:
                    continue
        
        # Try with just the first part of the name
        simple_name = channel_name.split('.')[0]
        for domain in self.config['stream']['domains']:
            url = f"https://{domain}/live/{simple_name}/chunks.m3u8"
            if self.session_id:
                url += f"?{self.config['stream']['session_param']}={self.session_id}"
            channel['stream_url'] = url
            return True
        
        return False

    def save_m3u(self, filename=None):
        """Save channels to M3U file"""
        filename = filename or self.config['output']['m3u']
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("#EXTM3U\n")
            f.write(f"#PLAYLIST: Aparatchi.com Channels\n")
            f.write(f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            if self.session_id:
                f.write(f"# Session ID: {self.session_id}\n")
            f.write(f"# Channels: {len(self.channels)}\n\n")
            
            # Group by category
            categories = {}
            for ch in self.channels:
                if ch['category'] not in categories:
                    categories[ch['category']] = []
                categories[ch['category']].append(ch)
            
            for category, channels in categories.items():
                f.write(f"# --- {category} ({len(channels)}) ---\n")
                
                for ch in channels:
                    if not ch.get('stream_url'):
                        continue
                    
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
        
        print(f"✅ Saved M3U: {filename}")

    def save_json(self, filename=None):
        """Save channels to JSON file"""
        filename = filename or self.config['output']['json']
        
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
    print("║   Aparatchi M3U Generator v2.0    ║")
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
