# Gumbo (GUM)

**General User Models (GUM)** learn about you by observing your interactions with your computer. Gumbo uses this architecture to infer new propositions about a user from multimodal observations, retrieve related context, and continuously revise its understanding.

## Features
- **Multimodal Learning**: Captures and processes text and visual data (screenshots) to understand user context.
- **Cross-Platform**: Built with Python, supports macOS (primary) and other platforms.
- **Privacy-First**: Designed with user privacy in mind (requires user-provided API keys).
- **Unified AI Client**: Seamlessly switches between Text (Azure/OpenAI) and Vision (OpenRouter) providers.

## Installation

### Prerequisites
- Python 3.8+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (required for some OCR features)

### Setup
1. **Clone the repository**:
   ```bash
   git clone https://github.com/ArnavS-22/gumboapp.git
   cd gumboapp
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   # OR
   pip install .
   ```

3. **Configuration**:
   The application requires API keys for AI services. It will prompt you for these on first run, or you can set them as environment variables:
   - `OPENAI_API_KEY`: For text processing
   - `OPENROUTER_API_KEY`: For vision/multimodal processing (optional)
   - `AZURE_OPENAI_API_KEY` & `AZURE_OPENAI_ENDPOINT`: For Azure OpenAI (optional)

## Usage

To start the application:

```bash
python start_gum.py
```

Or if installed as a package:

```bash
gum
```

## Contributing
We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to submit pull requests, report issues, and our code of conduct.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Authors
- Omar Shaikh
- Arnav Sharma
