# -*- coding: utf-8 -*-
"""
Hardware module for communicating with the Bluefors Remote Access Control API Gen. 1.
"""

import urllib.request
import json
import logging
from qudi.core.module import Base
from qudi.core.configoption import ConfigOption


class BlueforsAPI(Base):
    """
    Qudi Hardware module to interface with Bluefors API.
    """

    host = ConfigOption(name='host', default='localhost')
    port = ConfigOption(name='port', default=49099)
    api_key = ConfigOption(name='api_key', missing='warn')

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self._base_url = None

    def on_activate(self):
        self._base_url = f"http://{self.host}:{self.port}/values"
        self.log.info(f"BlueforsAPI activated with host: {self.host}:{self.port}")

    def on_deactivate(self):
        self.log.info("BlueforsAPI deactivated.")

    def get_value(self, target: str):
        """
        Fetch a single node value from the Bluefors API.
        target: The value tree node, e.g., 'mapper.bf.flow'
        Returns the parsed JSON data dictionary for the node, or None if error.
        """
        if not self.api_key:
            self.log.warning("No API key provided for Bluefors API.")
            return None

        url = f"{self._base_url}/{target}?key={self.api_key}&style=flat"
        
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=5.0) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    return data.get('data', {})
                else:
                    self.log.error(f"Failed to fetch {target}: HTTP {response.status}")
                    return None
        except Exception as e:
            self.log.error(f"Error fetching {target} from Bluefors API: {e}")
            return None

    def get_values(self, targets: list):
        """
        Fetch multiple nodes and return a dict mapping target to its value.
        """
        results = {}
        for target in targets:
            node_data = self.get_value(target)
            if node_data and target in node_data:
                content = node_data[target].get('content', {})
                latest_valid = content.get('latest_valid_value', {})
                if 'value' in latest_valid:
                    try:
                        results[target] = float(latest_valid['value'])
                    except ValueError:
                        results[target] = latest_valid['value']
                else:
                    results[target] = None
            else:
                results[target] = None
        return results
