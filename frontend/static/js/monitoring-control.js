/**
 * Gumbo Monitoring Control Module
 * Provides monitoring start/stop functionality and status polling
 * Integrates seamlessly with the existing Gumbo frontend
 */

class GumboMonitoringControl {
    constructor() {
        // Configuration
        this.localBackendUrl = 'http://localhost:8000';
        this.hostedDomain = 'https://gumbo.app';
        this.pollingInterval = 10000; // 10 seconds
        this.maxRetries = 3;
        this.retryDelay = 2000;

        // State
        this.isConnected = false;
        this.isMonitoring = false;
        this.monitoringStatus = null;
        this.pollingTimer = null;
        this.retryCount = 0;
        this.connectionCheckTimer = null;

        // UI Elements
        this.monitoringContainer = null;
        this.statusIndicator = null;
        this.toggleButton = null;
        this.statusText = null;
        this.connectionStatus = null;

        // Initialize
        this.init();
    }

    /**
     * Initialize the monitoring control module
     */
    async init() {
        try {
            console.log('Gumbo Monitoring Control: Starting initialization...');
            // Check if we should load on this domain
            if (this.shouldLoadOnCurrentDomain()) {
                console.log('Gumbo Monitoring Control: Domain check passed, setting up UI...');
                // Wait for DOM to be ready
                if (document.readyState === 'loading') {
                    console.log('Gumbo Monitoring Control: DOM loading, adding event listener...');
                    document.addEventListener('DOMContentLoaded', () => this.setupUI());
                } else {
                    console.log('Gumbo Monitoring Control: DOM ready, setting up UI immediately...');
                    this.setupUI();
                }

                // Check initial connection
                await this.checkConnection();

                // Start connection monitoring
                this.startConnectionMonitoring();

                console.log('Gumbo Monitoring Control initialized successfully');
            } else {
                console.log('Gumbo Monitoring Control: Not loading on this domain');
            }
        } catch (error) {
            console.error('Failed to initialize monitoring control:', error);
        }
    }

    /**
     * Check if monitoring control should load on current domain
     */
    shouldLoadOnCurrentDomain() {
        const hostname = window.location.hostname;
        console.log('Checking domain:', hostname);
        const shouldLoad = hostname === 'gumbo.app' ||
            hostname === 'www.gumbo.app' ||
            hostname === 'localhost' ||
            hostname === '127.0.0.1';
        console.log('Should load monitoring control:', shouldLoad);
        return shouldLoad;
    }

    /**
     * Set up the monitoring control UI
     */
    setupUI() {
        console.log('Gumbo Monitoring Control: Setting up UI...');
        try {
            // Create monitoring container
            console.log('Gumbo Monitoring Control: Creating monitoring container...');
            this.createMonitoringContainer();

            // Just add it to the body immediately - no fancy insertion
            console.log('Gumbo Monitoring Control: Adding to body...');
            document.body.appendChild(this.monitoringContainer);

            // Set up event listeners
            console.log('Gumbo Monitoring Control: Setting up event listeners...');
            this.setupEventListeners();

            // Initial status update
            console.log('Gumbo Monitoring Control: UI setup completed successfully');

            // Add a simple test button for debugging
            setTimeout(() => {
                console.log('Gumbo Monitoring Control: Adding debug button...');
                const testButton = document.createElement('button');
                testButton.textContent = 'DEBUG: Monitoring Control';
                testButton.style.cssText = 'position: fixed; top: 10px; right: 10px; z-index: 9999; background: #666; color: white; padding: 8px; border: none; cursor: pointer; font-size: 12px; border-radius: 4px;';
                testButton.onclick = () => {
                    console.log('Monitoring control debug button clicked!');
                    console.log('Current state:', {
                        isConnected: this.isConnected,
                        isMonitoring: this.isMonitoring,
                        monitoringStatus: this.monitoringStatus
                    });
                };
                document.body.appendChild(testButton);
            }, 1000);

        } catch (error) {
            console.error('Gumbo Monitoring Control: Error in setupUI:', error);
        }
    }

    /**
     * Create the monitoring control container
     */
    createMonitoringContainer() {
        console.log('Gumbo Monitoring Control: Creating monitoring container...');
        this.monitoringContainer = document.createElement('div');
        this.monitoringContainer.className = 'monitoring-control-container';
        this.monitoringContainer.style.cssText = 'position: fixed; top: 100px; left: 20px; z-index: 9998; border: 2px solid #ddd; padding: 20px; margin: 20px; background: white; font-size: 14px; max-width: 400px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); border-radius: 8px;';
        this.monitoringContainer.innerHTML = `
            <div class="monitoring-header">
                <h3>
                    <i class="fas fa-eye"></i>
                    Local Monitoring Control
                </h3>
                <p>Control your local GUM monitoring agent from this hosted interface</p>
            </div>
            
            <div class="monitoring-status">
                <div class="status-row">
                    <div class="status-label">Connection:</div>
                    <div class="status-value">
                        <span class="connection-indicator" id="connectionIndicator">
                            <i class="fas fa-circle"></i>
                            <span class="connection-text">Checking...</span>
                        </span>
                    </div>
                </div>
                
                <div class="status-row">
                    <div class="status-label">Monitoring:</div>
                    <div class="status-value">
                        <span class="monitoring-indicator" id="monitoringIndicator">
                            <i class="fas fa-circle"></i>
                            <span class="monitoring-text">Unknown</span>
                        </span>
                    </div>
                </div>
                
                <div class="monitoring-details" id="monitoringDetails" style="display: none;">
                    <div class="detail-row">
                        <span class="detail-label">User:</span>
                        <span class="detail-value" id="monitoringUser">-</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Model:</span>
                        <span class="detail-value" id="monitoringModel">-</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Uptime:</span>
                        <span class="detail-value" id="monitoringUptime">-</span>
                    </div>
                </div>
            </div>
            
            <div class="monitoring-actions">
                <button class="btn-primary monitoring-toggle" id="monitoringToggle" disabled>
                    <i class="fas fa-play"></i>
                    <span class="toggle-text">Start Monitoring</span>
                </button>
                
                                 <div class="monitoring-inputs" id="monitoringInputs" style="display: block;">
                    <div class="input-group">
                        <label for="userNameInput">User Name:</label>
                        <input type="text" id="userNameInput" placeholder="Enter your name" 
                               class="form-input" maxlength="50">
                    </div>
                    <div class="input-group">
                        <label for="modelSelect">AI Model:</label>
                        <select id="modelSelect" class="form-select">
                            <option value="gpt-4o-mini">GPT-4o Mini (Default)</option>
                            <option value="gpt-4o">GPT-4o</option>
                            <option value="gpt-4-turbo">GPT-4 Turbo</option>
                            <option value="claude-3-haiku">Claude 3 Haiku</option>
                        </select>
                    </div>
                </div>
            </div>
            
            <div class="monitoring-message" id="monitoringMessage" style="display: none;">
                <div class="message-content">
                    <i class="message-icon"></i>
                    <span class="message-text"></span>
                </div>
            </div>
        `;

        // Store references to important elements
        this.connectionIndicator = this.monitoringContainer.querySelector('#connectionIndicator');
        this.monitoringIndicator = this.monitoringContainer.querySelector('#monitoringIndicator');
        this.monitoringToggle = this.monitoringContainer.querySelector('#monitoringToggle');
        this.monitoringDetails = this.monitoringContainer.querySelector('#monitoringDetails');
        this.monitoringMessage = this.monitoringContainer.querySelector('#monitoringMessage');
        this.userNameInput = this.monitoringContainer.querySelector('#userNameInput');
        this.modelSelect = this.monitoringContainer.querySelector('#modelSelect');
        this.monitoringInputs = this.monitoringContainer.querySelector('#monitoringInputs');
    }

    /**
     * Insert the monitoring control into the home tab
     */
    insertIntoHomeTab() {
        console.log('Gumbo Monitoring Control: Inserting into home tab...');

        // Try multiple ways to find the home panel
        let homePanel = document.getElementById('home-panel');
        if (!homePanel) {
            homePanel = document.querySelector('[id*="home"]');
        }
        if (!homePanel) {
            homePanel = document.querySelector('.tab-panel');
        }

        console.log('Gumbo Monitoring Control: Home panel found:', !!homePanel, homePanel?.id || homePanel?.className);

        if (homePanel) {
            // Try multiple ways to find home content
            let homeContent = homePanel.querySelector('.home-content');
            if (!homeContent) {
                homeContent = homePanel.querySelector('[class*="content"]');
            }
            if (!homeContent) {
                homeContent = homePanel;
            }

            console.log('Gumbo Monitoring Control: Home content found:', !!homeContent, homeContent?.className);

            if (homeContent) {
                // Try to find welcome section
                let welcomeSection = homeContent.querySelector('.welcome-section');
                if (!welcomeSection) {
                    welcomeSection = homeContent.querySelector('[class*="welcome"]');
                }
                if (!welcomeSection) {
                    welcomeSection = homeContent.querySelector('h3');
                }

                console.log('Gumbo Monitoring Control: Welcome section found:', !!welcomeSection, welcomeSection?.className || welcomeSection?.tagName);

                if (welcomeSection) {
                    console.log('Gumbo Monitoring Control: Inserting after welcome section...');
                    welcomeSection.parentNode.insertBefore(this.monitoringContainer, welcomeSection.nextSibling);
                } else {
                    console.log('Gumbo Monitoring Control: No welcome section, appending to home content...');
                    homeContent.appendChild(this.monitoringContainer);
                }
                console.log('Gumbo Monitoring Control: Successfully inserted into home tab');
            } else {
                console.error('Gumbo Monitoring Control: Could not find home-content');
                // Fallback: try to insert at the top of the page
                console.log('Gumbo Monitoring Control: Trying fallback insertion...');
                const body = document.body;
                if (body) {
                    body.insertBefore(this.monitoringContainer, body.firstChild);
                    console.log('Gumbo Monitoring Control: Inserted at top of body as fallback');
                }
            }
        } else {
            console.error('Gumbo Monitoring Control: Could not find home-panel');
            // Fallback: try to insert at the top of the page
            console.log('Gumbo Monitoring Control: Trying fallback insertion...');
            const body = document.body;
            if (body) {
                body.insertBefore(this.monitoringContainer, body.firstChild);
                console.log('Gumbo Monitoring Control: Inserted at top of body as fallback');
            }
        }
    }

    /**
     * Set up event listeners
     */
    setupEventListeners() {
        if (this.monitoringToggle) {
            this.monitoringToggle.addEventListener('click', () => this.handleToggleClick());
        }

        if (this.userNameInput) {
            this.userNameInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.handleToggleClick();
                }
            });
        }
    }

    /**
     * Handle monitoring toggle button click
     */
    async handleToggleClick() {
        if (!this.isConnected) {
            this.showMessage('Please ensure your local Gumbo backend is running', 'warning');
            return;
        }

        if (this.isMonitoring) {
            await this.stopMonitoring();
        } else {
            await this.startMonitoring();
        }
    }

    /**
     * Start monitoring
     */
    async startMonitoring() {
        try {
            const userName = this.userNameInput?.value?.trim();
            if (!userName) {
                this.showMessage('Please enter a user name', 'warning');
                this.userNameInput?.focus();
                return;
            }

            this.setButtonLoading(true, 'Starting...');
            this.hideMessage();

            const response = await this.apiCall('/monitoring/start', {
                method: 'POST',
                body: JSON.stringify({
                    user_name: userName,
                    model: this.modelSelect?.value || 'gpt-4o-mini',
                    debug: false
                })
            });

            if (response.success) {
                this.showMessage(`Monitoring started successfully for ${userName}`, 'success');
                this.isMonitoring = true;
                this.monitoringStatus = response;

                // Hide inputs after successful start
                this.monitoringInputs.style.display = 'none';

                // Start status polling
                this.startStatusPolling();
            } else {
                throw new Error(response.message || 'Failed to start monitoring');
            }
        } catch (error) {
            console.error('Failed to start monitoring:', error);
            this.showMessage(this.getErrorMessage(error), 'error');
        } finally {
            this.setButtonLoading(false);
            this.updateUI();
        }
    }

    /**
     * Stop monitoring
     */
    async stopMonitoring() {
        try {
            this.setButtonLoading(true, 'Stopping...');
            this.hideMessage();

            const response = await this.apiCall('/monitoring/stop', {
                method: 'POST'
            });

            if (response.success) {
                this.showMessage('Monitoring stopped successfully', 'success');
                this.isMonitoring = false;
                this.monitoringStatus = null;

                // Show inputs after stopping
                this.monitoringInputs.style.display = 'block';

                // Stop status polling
                this.stopStatusPolling();
            } else {
                throw new Error(response.message || 'Failed to stop monitoring');
            }
        } catch (error) {
            console.error('Failed to stop monitoring:', error);
            this.showMessage(this.getErrorMessage(error), 'error');
        } finally {
            this.setButtonLoading(false);
            this.updateUI();
        }
    }

    /**
     * Check connection to local backend
     */
    async checkConnection() {
        try {
            const response = await fetch(`${this.localBackendUrl}/health`, {
                method: 'GET',
                mode: 'cors',
                headers: {
                    'Content-Type': 'application/json'
                },
                signal: AbortSignal.timeout(5000) // 5 second timeout
            });

            if (response.ok) {
                this.isConnected = true;
                this.retryCount = 0;

                // Check monitoring status if connected
                await this.checkMonitoringStatus();
            } else {
                this.isConnected = false;
                this.isMonitoring = false;
            }
        } catch (error) {
            this.isConnected = false;
            this.isMonitoring = false;

            if (error.name === 'AbortError') {
                console.log('Connection check timed out');
            } else if (error.name === 'TypeError' && error.message.includes('Failed to fetch')) {
                console.log('CORS or connection error - local backend not reachable');
            } else {
                console.error('Connection check error:', error);
            }
        }

        this.updateUI();
    }

    /**
     * Check current monitoring status
     */
    async checkMonitoringStatus() {
        try {
            const response = await this.apiCall('/monitoring/status', {
                method: 'GET'
            });

            this.monitoringStatus = response;
            this.isMonitoring = response.is_running;

            // Start polling if monitoring is running
            if (this.isMonitoring && !this.pollingTimer) {
                this.startStatusPolling();
            } else if (!this.isMonitoring && this.pollingTimer) {
                this.stopStatusPolling();
            }
        } catch (error) {
            console.error('Failed to check monitoring status:', error);
            this.isMonitoring = false;
            this.monitoringStatus = null;
        }

        this.updateUI();
    }

    /**
     * Start status polling
     */
    startStatusPolling() {
        if (this.pollingTimer) {
            clearInterval(this.pollingTimer);
        }

        this.pollingTimer = setInterval(async () => {
            if (this.isConnected && this.isMonitoring) {
                await this.checkMonitoringStatus();
            }
        }, this.pollingInterval);

        console.log('Started monitoring status polling');
    }

    /**
     * Stop status polling
     */
    stopStatusPolling() {
        if (this.pollingTimer) {
            clearInterval(this.pollingTimer);
            this.pollingTimer = null;
            console.log('Stopped monitoring status polling');
        }
    }

    /**
     * Start connection monitoring
     */
    startConnectionMonitoring() {
        // Check connection every 30 seconds
        this.connectionCheckTimer = setInterval(() => {
            this.checkConnection();
        }, 30000);
    }

    /**
     * Stop connection monitoring
     */
    stopConnectionMonitoring() {
        if (this.connectionCheckTimer) {
            clearInterval(this.connectionCheckTimer);
            this.connectionCheckTimer = null;
        }
    }

    /**
     * Make API call to local backend
     */
    async apiCall(endpoint, options = {}) {
        const url = `${this.localBackendUrl}${endpoint}`;

        try {
            const response = await fetch(url, {
                mode: 'cors',
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options,
                signal: AbortSignal.timeout(10000) // 10 second timeout
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error('Request timed out');
            }
            throw error;
        }
    }

    /**
     * Update the UI based on current state
     */
    updateUI() {
        this.updateConnectionIndicator();
        this.updateMonitoringIndicator();
        this.updateToggleButton();
        this.updateMonitoringDetails();
    }

    /**
     * Update connection indicator
     */
    updateConnectionIndicator() {
        if (!this.connectionIndicator) return;

        const icon = this.connectionIndicator.querySelector('i');
        const text = this.connectionIndicator.querySelector('.connection-text');

        if (this.isConnected) {
            icon.className = 'fas fa-circle';
            icon.style.color = 'var(--success-color)';
            text.textContent = 'Connected';
            text.style.color = 'var(--success-color)';
        } else {
            icon.className = 'fas fa-circle';
            icon.style.color = 'var(--error-color)';
            text.textContent = 'Disconnected';
            text.style.color = 'var(--error-color)';
        }
    }

    /**
     * Update monitoring indicator
     */
    updateMonitoringIndicator() {
        if (!this.monitoringIndicator) return;

        const icon = this.monitoringIndicator.querySelector('i');
        const text = this.monitoringIndicator.querySelector('.monitoring-text');

        if (this.isMonitoring) {
            icon.className = 'fas fa-circle';
            icon.style.color = 'var(--success-color)';
            text.textContent = 'Active';
            text.style.color = 'var(--success-color)';
        } else {
            icon.className = 'fas fa-circle';
            icon.style.color = 'var(--text-muted)';
            text.textContent = 'Inactive';
            text.style.color = 'var(--text-muted)';
        }
    }

    /**
     * Update toggle button
     */
    updateToggleButton() {
        if (!this.monitoringToggle) return;

        const icon = this.monitoringToggle.querySelector('i');
        const text = this.monitoringToggle.querySelector('.toggle-text');

        if (!this.isConnected) {
            this.monitoringToggle.disabled = true;
            this.monitoringToggle.className = 'btn-primary monitoring-toggle disabled';
            icon.className = 'fas fa-exclamation-triangle';
            text.textContent = 'Backend Unavailable';
        } else if (this.isMonitoring) {
            this.monitoringToggle.disabled = false;
            this.monitoringToggle.className = 'btn-danger monitoring-toggle';
            icon.className = 'fas fa-stop';
            text.textContent = 'Stop Monitoring';
        } else {
            this.monitoringToggle.disabled = false;
            this.monitoringToggle.className = 'btn-primary monitoring-toggle';
            icon.className = 'fas fa-play';
            text.textContent = 'Start Monitoring';
        }
    }

    /**
     * Update monitoring details
     */
    updateMonitoringDetails() {
        if (!this.monitoringDetails) return;

        if (this.isMonitoring && this.monitoringStatus) {
            this.monitoringDetails.style.display = 'block';

            // Update user name
            const userElement = this.monitoringDetails.querySelector('#monitoringUser');
            if (userElement) {
                userElement.textContent = this.monitoringStatus.user_name || '-';
            }

            // Update model
            const modelElement = this.monitoringDetails.querySelector('#monitoringModel');
            if (modelElement) {
                modelElement.textContent = this.monitoringStatus.model || '-';
            }

            // Update uptime
            const uptimeElement = this.monitoringDetails.querySelector('#monitoringUptime');
            if (uptimeElement && this.monitoringStatus.uptime_seconds) {
                uptimeElement.textContent = this.formatUptime(this.monitoringStatus.uptime_seconds);
            }
        } else {
            this.monitoringDetails.style.display = 'none';
        }
    }

    /**
     * Set button loading state
     */
    setButtonLoading(loading, text = '') {
        if (!this.monitoringToggle) return;

        if (loading) {
            this.monitoringToggle.disabled = true;
            this.monitoringToggle.classList.add('loading');
            if (text) {
                this.monitoringToggle.querySelector('.toggle-text').textContent = text;
            }
        } else {
            this.monitoringToggle.disabled = false;
            this.monitoringToggle.classList.remove('loading');
            this.updateToggleButton(); // This will restore the correct text
        }
    }

    /**
     * Show message
     */
    showMessage(message, type = 'info') {
        if (!this.monitoringMessage) return;

        const icon = this.monitoringMessage.querySelector('.message-icon');
        const text = this.monitoringMessage.querySelector('.message-text');

        // Set icon and class based on type
        icon.className = `fas ${this.getMessageIcon(type)}`;
        this.monitoringMessage.className = `monitoring-message message-${type}`;
        text.textContent = message;

        this.monitoringMessage.style.display = 'block';

        // Auto-hide after 5 seconds for success/info messages
        if (type === 'success' || type === 'info') {
            setTimeout(() => this.hideMessage(), 5000);
        }
    }

    /**
     * Hide message
     */
    hideMessage() {
        if (this.monitoringMessage) {
            this.monitoringMessage.style.display = 'none';
        }
    }

    /**
     * Get message icon based on type
     */
    getMessageIcon(type) {
        switch (type) {
            case 'success': return 'fa-check-circle';
            case 'error': return 'fa-exclamation-circle';
            case 'warning': return 'fa-exclamation-triangle';
            case 'info': return 'fa-info-circle';
            default: return 'fa-info-circle';
        }
    }

    /**
     * Get error message from error object
     */
    getErrorMessage(error) {
        if (error.message) {
            return error.message;
        }

        if (error.name === 'TypeError' && error.message.includes('Failed to fetch')) {
            return 'Cannot connect to local backend. Please ensure Gumbo is running on your machine.';
        }

        return 'An unexpected error occurred';
    }

    /**
     * Format uptime in human-readable format
     */
    formatUptime(seconds) {
        if (seconds < 60) {
            return `${seconds}s`;
        } else if (seconds < 3600) {
            const minutes = Math.floor(seconds / 60);
            return `${minutes}m ${seconds % 60}s`;
        } else {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${hours}h ${minutes}m`;
        }
    }

    /**
     * Cleanup resources
     */
    destroy() {
        this.stopStatusPolling();
        this.stopConnectionMonitoring();

        if (this.monitoringContainer && this.monitoringContainer.parentNode) {
            this.monitoringContainer.parentNode.removeChild(this.monitoringContainer);
        }
    }
}

// Simple test to confirm the script is loading
alert('MONITORING CONTROL SCRIPT IS LOADING!');

// Initialize monitoring control when DOM is ready and main app is ready
document.addEventListener('DOMContentLoaded', () => {
    // Wait for the main app to be ready
    const waitForApp = () => {
        if (window.gumboApp) {
            console.log('Gumbo Monitoring Control: Main app ready, initializing...');
            // Initialize monitoring control on supported domains
            window.gumboMonitoring = new GumboMonitoringControl();

            // Expose to global scope for debugging
            window.gumboMonitoringControl = window.gumboMonitoring;

            console.log('Gumbo Monitoring Control loaded');
        } else {
            console.log('Gumbo Monitoring Control: Waiting for main app...');
            setTimeout(waitForApp, 100);
        }
    };

    waitForApp();
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = GumboMonitoringControl;
}
