/**
 * Gumbo AI Assistant - Production Grade Chat Interface
 * Integrates with GUM behavioral data for personalized insights
 */

class GumboChat {
    constructor() {
        this.apiBaseUrl = window.GUM_CONFIG?.apiBaseUrl || 'http://localhost:8000';
        this.messages = [];
        this.isTyping = false;
        this.chatHistory = [];
        this.maxHistory = 50;

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.loadChatHistory();
        this.addWelcomeMessage();
    }

    setupEventListeners() {
        // Chat input
        const chatInput = document.getElementById('chatInput');
        const sendButton = document.getElementById('sendChatBtn');
        const chatContainer = document.getElementById('chatMessages');

        if (chatInput) {
            chatInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });

            // Auto-resize textarea
            chatInput.addEventListener('input', () => {
                chatInput.style.height = 'auto';
                chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
            });
        }

        if (sendButton) {
            sendButton.addEventListener('click', () => this.sendMessage());
        }

        // Auto-scroll to bottom
        if (chatContainer) {
            const observer = new MutationObserver(() => {
                chatContainer.scrollTop = chatContainer.scrollHeight;
            });
            observer.observe(chatContainer, { childList: true, subtree: true });
        }
    }

    addWelcomeMessage() {
        const welcomeMessage = {
            type: 'assistant',
            content: `Hi! I'm your Gumbo AI assistant. I've been learning about your behavior patterns and can help you understand your productivity, workflow, and habits. 

Try asking me:
• "When am I most productive?"
• "What apps do I use most during work?"
• "How can I optimize my workflow?"
• "Show me my recent behavior patterns"`,
            timestamp: new Date()
        };
        this.addMessage(welcomeMessage);
    }

    async sendMessage() {
        const input = document.getElementById('chatInput');
        const sendBtn = document.getElementById('sendChatBtn');

        if (!input || this.isTyping) return;

        const message = input.value.trim();
        if (!message) return;

        // Add user message
        const userMessage = {
            type: 'user',
            content: message,
            timestamp: new Date()
        };
        this.addMessage(userMessage);

        // Clear input and disable
        input.value = '';
        input.disabled = true;
        sendBtn.disabled = true;
        this.isTyping = true;

        try {
            // Get behavioral context first
            const context = await this.getBehavioralContext(message);

            // Send to AI for response
            const response = await this.getAIResponse(message, context);

            // Add AI response
            const aiMessage = {
                type: 'assistant',
                content: response,
                timestamp: new Date()
            };
            this.addMessage(aiMessage);

        } catch (error) {
            console.error('Chat error:', error);
            const errorMessage = {
                type: 'assistant',
                content: 'Sorry, I encountered an error. Please try again.',
                timestamp: new Date()
            };
            this.addMessage(errorMessage);
        } finally {
            // Re-enable input
            input.disabled = false;
            sendBtn.disabled = false;
            this.isTyping = false;
            input.focus();
        }
    }

    async getBehavioralContext(query) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/query`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: query,
                    limit: 5,
                    mode: 'OR'
                })
            });

            if (!response.ok) {
                throw new Error('Failed to get behavioral context');
            }

            const data = await response.json();
            return this.formatContext(data);
        } catch (error) {
            console.warn('Could not get behavioral context:', error);
            return 'No recent behavioral data available.';
        }
    }

    formatContext(data) {
        if (!data.propositions || data.propositions.length === 0) {
            return 'No relevant behavioral patterns found.';
        }

        let context = 'Based on your recent behavior:\n\n';
        data.propositions.forEach((prop, index) => {
            context += `${index + 1}. ${prop.text}\n`;
            if (prop.confidence) {
                context += `   Confidence: ${(prop.confidence * 100).toFixed(1)}%\n`;
            }
            context += '\n';
        });

        return context;
    }

    async getAIResponse(message, context) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/observations/text`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    content: `User Query: ${message}\n\nBehavioral Context:\n${context}\n\nPlease provide a helpful, personalized response based on the user's behavioral data. Be conversational and actionable.`,
                    user_name: 'Arnav Sharma',
                    observer_name: 'gumbo_chat'
                })
            });

            if (!response.ok) {
                throw new Error('Failed to get AI response');
            }

            const data = await response.json();
            return data.message || 'I understand your question. Let me analyze your behavior patterns and get back to you.';
        } catch (error) {
            console.error('AI response error:', error);
            return 'I\'m having trouble accessing your behavioral data right now. Please try again in a moment.';
        }
    }

    addMessage(message) {
        this.messages.push(message);
        this.chatHistory.push(message);

        // Keep history manageable
        if (this.chatHistory.length > this.maxHistory) {
            this.chatHistory.shift();
        }

        this.saveChatHistory();
        this.renderMessage(message);
    }

    renderMessage(message) {
        const container = document.getElementById('chatMessages');
        if (!container) return;

        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${message.type}-message`;

        const timestamp = message.timestamp.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit'
        });

        messageDiv.innerHTML = `
            <div class="message-content">
                <div class="message-text">${this.formatMessage(message.content)}</div>
                <div class="message-time">${timestamp}</div>
            </div>
        `;

        container.appendChild(messageDiv);
    }

    formatMessage(content) {
        // Convert line breaks to <br> tags
        return content.replace(/\n/g, '<br>');
    }

    saveChatHistory() {
        try {
            localStorage.setItem('gumbo_chat_history', JSON.stringify(this.chatHistory));
        } catch (error) {
            console.warn('Could not save chat history:', error);
        }
    }

    loadChatHistory() {
        try {
            const saved = localStorage.getItem('gumbo_chat_history');
            if (saved) {
                this.chatHistory = JSON.parse(saved);
                // Convert timestamp strings back to Date objects
                this.chatHistory.forEach(msg => {
                    msg.timestamp = new Date(msg.timestamp);
                });
            }
        } catch (error) {
            console.warn('Could not load chat history:', error);
        }
    }

    clearHistory() {
        this.chatHistory = [];
        this.messages = [];
        localStorage.removeItem('gumbo_chat_history');

        const container = document.getElementById('chatMessages');
        if (container) {
            container.innerHTML = '';
        }

        this.addWelcomeMessage();
    }

    sendSuggestion(suggestion) {
        const input = document.getElementById('chatInput');
        if (input) {
            input.value = suggestion;
            this.sendMessage();
        }
    }
}

// Initialize chat when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.gumboChat = new GumboChat();
}); 