#!/usr/bin/env python3
"""
Gumbo Setup Wizard

A simple command-line setup wizard to configure API keys and initial settings
for new users. This eliminates the need for environment variables.
"""

import os
import sys
import json
from pathlib import Path

# Add the gum directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'gum'))

try:
    from config_manager import get_config_manager
except ImportError:
    print("Error: Could not import config manager. Make sure you're running this from the project root.")
    sys.exit(1)

def print_banner():
    """Print the setup wizard banner."""
    print("=" * 60)
    print("           GUMBO GUM SETUP WIZARD")
    print("=" * 60)
    print()
    print("Welcome! This wizard will help you configure Gumbo GUM.")
    print("You'll need at least one AI API key to get started.")
    print()

def get_user_input(prompt: str, default: str = "") -> str:
    """Get user input with a default value."""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        return input(f"{prompt}: ").strip()

def validate_api_key(api_key: str) -> bool:
    """Basic validation for API keys."""
    if not api_key:
        return False
    if len(api_key) < 20:  # Most API keys are longer
        return False
    return True

def setup_api_keys(config_manager):
    """Set up API keys for the user."""
    print("API Key Configuration")
    print("-" * 30)
    print()
    
    # Check if we already have API keys
    existing_keys = []
    for provider in ['openai', 'anthropic', 'openrouter']:
        if config_manager.get_api_key(provider):
            existing_keys.append(provider)
    
    if existing_keys:
        print(f"Found existing API keys for: {', '.join(existing_keys)}")
        print()
    
    # OpenAI setup
    print("1. OpenAI API Key (Recommended)")
    print("   Get your key from: https://platform.openai.com/api-keys")
    print()
    
    openai_key = get_user_input("Enter your OpenAI API key (or press Enter to skip)")
    if openai_key and validate_api_key(openai_key):
        config_manager.set_api_key("openai", openai_key)
        print("✓ OpenAI API key saved!")
    elif openai_key:
        print("⚠ Invalid API key format. Skipping OpenAI setup.")
    else:
        print("⏭ Skipping OpenAI setup.")
    
    print()
    
    # Anthropic setup
    print("2. Anthropic API Key (Claude)")
    print("   Get your key from: https://console.anthropic.com/")
    print()
    
    anthropic_key = get_user_input("Enter your Anthropic API key (or press Enter to skip)")
    if anthropic_key and validate_api_key(anthropic_key):
        config_manager.set_api_key("anthropic", anthropic_key)
        print("✓ Anthropic API key saved!")
    elif anthropic_key:
        print("⚠ Invalid API key format. Skipping Anthropic setup.")
    else:
        print("⏭ Skipping Anthropic setup.")
    
    print()
    
    # OpenRouter setup
    print("3. OpenRouter API Key (Multiple Models)")
    print("   Get your key from: https://openrouter.ai/keys")
    print()
    
    openrouter_key = get_user_input("Enter your OpenRouter API key (or press Enter to skip)")
    if openrouter_key and validate_api_key(openrouter_key):
        config_manager.set_api_key("openrouter", openrouter_key)
        print("✓ OpenRouter API key saved!")
    elif openrouter_key:
        print("⚠ Invalid API key format. Skipping OpenRouter setup.")
    else:
        print("⏭ Skipping OpenRouter setup.")

def setup_user_preferences(config_manager):
    """Set up user preferences and settings."""
    print()
    print("User Preferences")
    print("-" * 20)
    print()
    
    # Default username
    current_user = config_manager.get_user_settings("Default User")
    default_username = current_user.get("default_username", "Default User")
    
    username = get_user_input("Enter your preferred username", default_username)
    if username:
        # Update the default user settings
        config_manager.update_user_settings(username, {
            "tracking_enabled": True,
            "default_username": username
        })
        print(f"✓ Username set to: {username}")
    
    print()
    
    # Screenshots directory
    current_dir = config_manager._load_config().get("app_settings", {}).get("screenshots_dir", "~/.cache/gum/screenshots")
    screenshots_dir = get_user_input("Screenshots directory", current_dir)
    if screenshots_dir:
        config = config_manager._load_config()
        if "app_settings" not in config:
            config["app_settings"] = {}
        config["app_settings"]["screenshots_dir"] = screenshots_dir
        config_manager._save_config(config)
        print(f"✓ Screenshots directory set to: {screenshots_dir}")

def setup_ai_providers(config_manager):
    """Set up AI provider preferences."""
    print()
    print("AI Provider Preferences")
    print("-" * 25)
    print()
    
    # Check what API keys we have
    available_providers = []
    for provider in ['openai', 'anthropic', 'openrouter']:
        if config_manager.get_api_key(provider):
            available_providers.append(provider)
    
    if not available_providers:
        print("⚠ No API keys configured. Please set up API keys first.")
        return
    
    print(f"Available providers: {', '.join(available_providers)}")
    print()
    
    # Text provider
    current_text = config_manager.get_provider("text")
    if current_text in available_providers:
        text_provider = get_user_input("Preferred text provider", current_text)
    else:
        text_provider = get_user_input("Preferred text provider", available_providers[0])
    
    if text_provider in available_providers:
        config_manager.set_provider("text", text_provider)
        print(f"✓ Text provider set to: {text_provider}")
    
    # Vision provider
    current_vision = config_manager.get_provider("vision")
    if current_vision in available_providers:
        vision_provider = get_user_input("Preferred vision provider", current_vision)
    else:
        vision_provider = get_user_input("Preferred vision provider", available_providers[0])
    
    if vision_provider in available_providers:
        config_manager.set_provider("vision", vision_provider)
        print(f"✓ Vision provider set to: {vision_provider}")

def show_summary(config_manager):
    """Show a summary of the configuration."""
    print()
    print("Configuration Summary")
    print("-" * 25)
    print()
    
    config = config_manager._load_config()
    
    # API Keys
    api_keys = config.get("api_keys", {})
    if api_keys:
        print("✓ API Keys configured:")
        for provider, key in api_keys.items():
            masked_key = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
            print(f"   {provider}: {masked_key}")
    else:
        print("⚠ No API keys configured")
    
    print()
    
    # Providers
    providers = config.get("ai_providers", {})
    if providers:
        print("✓ AI Providers:")
        for provider_type, provider_name in providers.items():
            print(f"   {provider_type}: {provider_name}")
    
    print()
    
    # App Settings
    app_settings = config.get("app_settings", {})
    if app_settings:
        print("✓ App Settings:")
        for key, value in app_settings.items():
            print(f"   {key}: {value}")
    
    print()
    
    # Check if configuration is complete
    if config_manager.is_configured():
        print("🎉 Configuration complete! You can now run Gumbo GUM.")
        print()
        print("Next steps:")
        print("1. Run 'python start_gum.py' to start the application")
        print("2. Or double-click 'start_gum.bat' (Windows)")
        print("3. Open your browser to the dashboard URL shown")
    else:
        print("⚠ Configuration incomplete. Please set up at least one API key.")
        print()
        print("You can run this setup wizard again anytime with:")
        print("   python setup_wizard.py")

def main():
    """Main setup wizard function."""
    try:
        print_banner()
        
        # Initialize config manager
        config_manager = get_config_manager()
        
        # Run setup steps
        setup_api_keys(config_manager)
        setup_user_preferences(config_manager)
        setup_ai_providers(config_manager)
        
        # Show summary
        show_summary(config_manager)
        
        print()
        print("=" * 60)
        print("Setup wizard completed!")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\nSetup cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during setup: {e}")
        print("Please check your configuration and try again.")
        sys.exit(1)

if __name__ == "__main__":
    main()
