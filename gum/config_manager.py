#!/usr/bin/env python3
"""
Configuration Manager for GUM System

Handles loading and saving application configuration and user settings
from local JSON files instead of environment variables.
"""

import json
import os
import logging
import stat
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

class ConfigManager:
    """Manages application configuration and user settings."""
    
    def __init__(self, config_dir: Optional[str] = None):
        """Initialize the configuration manager.
        
        Args:
            config_dir: Directory to store config files. Defaults to ~/.config/gum/
        """
        if config_dir is None:
            config_dir = os.path.expanduser("~/.config/gum/")
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.config_file = self.config_dir / "gum_config.json"
        self.users_file = self.config_dir / "users.json"
        
        # Initialize default configuration
        self._ensure_default_config()
        self._ensure_default_users()
    
    def _ensure_default_config(self):
        """Ensure default configuration exists."""
        if not self.config_file.exists():
            default_config = {
                "ai_providers": {
                    "text": "openai",
                    "vision": "openai"
                },
                "api_keys": {},
                "app_settings": {
                    "default_user": "Default User",
                    "screenshots_dir": "~/.cache/gum/screenshots",
                    "debug": False
                },
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            self._save_config(default_config)
    
    def _ensure_default_users(self):
        """Ensure default users file exists."""
        if not self.users_file.exists():
            default_users = {
                "Default User": {
                    "tracking_enabled": True,
                    "created_at": datetime.now().isoformat(),
                    "last_active": datetime.now().isoformat(),
                    "settings": {
                        "skip_when_visible": [],
                        "transcription_prompt": None,
                        "summary_prompt": None,
                        "model_name": "gpt-4o-mini"
                    }
                }
            }
            self._save_users(default_users)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Return default config if file is corrupted
            self._ensure_default_config()
            with open(self.config_file, 'r') as f:
                return json.load(f)
    
    def _save_config(self, config: Dict[str, Any]) -> None:
        """Save configuration to file."""
        config["updated_at"] = datetime.now().isoformat()
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)
        self._ensure_secure_permissions(self.config_file)
    
    def _load_users(self) -> Dict[str, Any]:
        """Load users from file."""
        try:
            with open(self.users_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            # Return default users if file is corrupted
            self._ensure_default_users()
            with open(self.users_file, 'r') as f:
                return json.load(f)
    
    def _save_users(self, users: Optional[Dict[str, Any]] = None) -> None:
        """Save users to file.
        
        Args:
            users: Users data to save. If None, loads current users from file.
        """
        if users is None:
            users = self._load_users()
        with open(self.users_file, 'w') as f:
            json.dump(users, f, indent=2)
        self._ensure_secure_permissions(self.users_file)

    def _ensure_secure_permissions(self, path: Path) -> None:
        """Restrict file permissions to owner read/write only."""
        try:
            current_mode = path.stat().st_mode
            desired_mode = stat.S_IRUSR | stat.S_IWUSR
            if current_mode & (stat.S_IRWXG | stat.S_IRWXO):
                logging.warning(f"Tightening permissions on sensitive file: {path}")
                os.chmod(path, desired_mode)
        except FileNotFoundError:
            return
        except Exception as e:
            logging.warning(f"Could not adjust permissions for {path}: {e}")
    
    def get_api_key(self, key_name: str) -> Optional[str]:
        """Get an API key by name.
        
        Args:
            key_name: Name of the API key (e.g., 'openai', 'anthropic')
            
        Returns:
            API key value or None if not found
        """
        config = self._load_config()
        return config.get("api_keys", {}).get(key_name)
    
    def set_api_key(self, key_name: str, value: str) -> None:
        """Set an API key.
        
        Args:
            key_name: Name of the API key
            value: API key value
        """
        config = self._load_config()
        if "api_keys" not in config:
            config["api_keys"] = {}
        config["api_keys"][key_name] = value
        self._save_config(config)
    
    def get_provider(self, provider_type: str) -> str:
        """Get the configured provider for a given type.
        
        Args:
            provider_type: Type of provider ('text' or 'vision')
            
        Returns:
            Provider name
        """
        config = self._load_config()
        return config.get("ai_providers", {}).get(provider_type, "openai")
    
    def set_provider(self, provider_type: str, provider_name: str) -> None:
        """Set the provider for a given type.
        
        Args:
            provider_type: Type of provider ('text' or 'vision')
            provider_name: Name of the provider
        """
        config = self._load_config()
        if "ai_providers" not in config:
            config["ai_providers"] = {}
        config["ai_providers"][provider_type] = provider_name
        self._save_config(config)
    
    def get_user_settings(self, username: str) -> Dict[str, Any]:
        """Get settings for a specific user.
        
        Args:
            username: Name of the user
            
        Returns:
            User settings dictionary
        """
        users = self._load_users()
        if username not in users:
            # Create default user settings
            users[username] = {
                "tracking_enabled": True,
                "created_at": datetime.now().isoformat(),
                "last_active": datetime.now().isoformat(),
                "settings": {
                    "skip_when_visible": [],
                    "transcription_prompt": None,
                    "summary_prompt": None,
                    "model_name": "gpt-4o-mini"
                }
            }
            self._save_users(users)
        
        return users[username]
    
    def update_user_settings(self, username: str, settings: Dict[str, Any]) -> None:
        """Update settings for a specific user.
        
        Args:
            username: Name of the user
            settings: New settings to apply
        """
        users = self._load_users()
        if username not in users:
            users[username] = {}
        
        users[username].update(settings)
        users[username]["last_active"] = datetime.now().isoformat()
        self._save_users(users)
    
    def is_configured(self) -> bool:
        """Check if the application is fully configured.
        
        Returns:
            True if all required configuration is present
        """
        config = self._load_config()
        api_keys = config.get("api_keys", {})
        
        # Check if we have at least one API key
        return len(api_keys) > 0
    
    def get_missing_config(self) -> list:
        """Get list of missing configuration items.
        
        Returns:
            List of missing configuration keys
        """
        config = self._load_config()
        api_keys = config.get("api_keys", {})
        
        missing = []
        if not api_keys:
            missing.append("api_keys")
        
        return missing
    
    def export_to_env(self) -> Dict[str, str]:
        """Export configuration as environment variables.
        
        Returns:
            Dictionary of environment variable names and values
        """
        config = self._load_config()
        env_vars = {}
        
        # Export API keys
        for key_name, value in config.get("api_keys", {}).items():
            if key_name == "openai":
                env_vars["OPENAI_API_KEY"] = value
                env_vars["GUM_LM_API_KEY"] = value
                env_vars["SCREEN_LM_API_KEY"] = value
            elif key_name == "anthropic":
                env_vars["ANTHROPIC_API_KEY"] = value
            elif key_name == "openrouter":
                env_vars["OPENROUTER_API_KEY"] = value
        
        # Export API bases if configured
        for key_name, value in config.get("api_keys", {}).items():
            if key_name == "openai":
                env_vars["GUM_LM_API_BASE"] = "https://api.openai.com/v1"
                env_vars["SCREEN_LM_API_BASE"] = "https://api.openai.com/v1"
            elif key_name == "anthropic":
                env_vars["GUM_LM_API_BASE"] = "https://api.anthropic.com"
            elif key_name == "openrouter":
                env_vars["GUM_LM_API_BASE"] = "https://openrouter.ai/api/v1"
        
        return env_vars

# Global instance
config_manager = ConfigManager()

def get_config_manager() -> ConfigManager:
    """Get the global configuration manager instance."""
    return config_manager
