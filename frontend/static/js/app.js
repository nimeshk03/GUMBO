/**
 * Gumbo - Frontend Application
 * Modern JavaScript application for video analysis and user behavior insights
 */

class GumboApp {
    constructor() {
        // Use configuration from injected global variable or fallback to default
        this.apiBaseUrl = window.GUMBO_CONFIG?.apiBaseUrl || 'http://localhost:8000';
        console.log('Gumbo Frontend initialized with API base URL:', this.apiBaseUrl);

        this.connectionStatus = 'connecting';
        this.uploadProgress = 0;
        this.currentStep = 1;
        this.selectedFile = null;
        this.toastTimeout = null;
        this.rateLimitInfo = {}; // Add rate limit tracking
        this.rateLimitTimers = {}; // Track countdown timers

        // Propositions pagination
        this.currentPropositionsPage = 1;

        // Tab management
        this.activeTab = 'home';
        // Theme management - handle migration from old theme key
        let theme = localStorage.getItem('gum-theme');
        if (!theme) {
            // Default to light theme
            theme = 'light';
            localStorage.setItem('gum-theme', theme);
        }
        this.theme = theme;

        // Text shimmer management
        this.textShimmerInstances = new Map();

        // Suggestion chat system
        this.activeSuggestionChats = {};
        this.currentChatId = null;
        this.currentSuggestionBatch = null;

        this.init();
    }

    async apiCall(url, options = {}) {
        try {
            const response = await fetch(url, options);

            if (response.status === 429) {
                const retryAfter = response.headers.get('Retry-After');
                const rateLimitLimit = response.headers.get('X-RateLimit-Limit');
                const rateLimitRemaining = response.headers.get('X-RateLimit-Remaining');
                const rateLimitReset = response.headers.get('X-RateLimit-Reset');

                const errorData = await response.json();

                this.handleRateLimit(url, retryAfter, errorData.detail, {
                    limit: rateLimitLimit,
                    remaining: rateLimitRemaining,
                    reset: rateLimitReset
                });
                throw new Error('Rate limited');
            }

            // Clear any rate limit info on success
            delete this.rateLimitInfo[url];
            this.updateRateLimitUI();

            return response;
        } catch (error) {
            if (error.message !== 'Rate limited') {
                this.showToast('❌ Connection error. Make sure Gumbo is running.', 'error');
            }
            throw error;
        }
    }

    handleRateLimit(endpoint, retryAfter, message, headers = {}) {
        const waitTime = parseInt(retryAfter) || 60;
        const resetTime = Date.now() + (waitTime * 1000);

        this.rateLimitInfo[endpoint] = {
            resetTime: resetTime,
            message: message,
            limit: headers.limit,
            remaining: headers.remaining,
            reset: headers.reset
        };

        this.showToast(`⏳ ${message}`, 'warning', waitTime * 1000);
        this.updateRateLimitUI();

        // Start countdown timer
        this.startRateLimitCountdown(endpoint, resetTime);

        // Auto-clear after wait time
        setTimeout(() => {
            delete this.rateLimitInfo[endpoint];
            this.updateRateLimitUI();
        }, waitTime * 1000);
    }

    startRateLimitCountdown(endpoint, resetTime) {
        // Clear existing timer for this endpoint
        if (this.rateLimitTimers[endpoint]) {
            clearInterval(this.rateLimitTimers[endpoint]);
        }

        // Start new countdown timer
        this.rateLimitTimers[endpoint] = setInterval(() => {
            const remainingTime = Math.ceil((resetTime - Date.now()) / 1000);

            if (remainingTime <= 0) {
                // Time's up, clear timer and re-enable
                clearInterval(this.rateLimitTimers[endpoint]);
                delete this.rateLimitTimers[endpoint];
                delete this.rateLimitInfo[endpoint];
                this.updateRateLimitUI();
                this.showToast('✅ Rate limit reset - you can try again!', 'success');
            } else {
                // Update UI with remaining time
                this.updateRateLimitUI();
            }
        }, 1000);
    }

    updateRateLimitUI() {
        // Update video upload button
        this.updateEndpointRateLimitUI('/observations/video', 'uploadBtn', 'Upload Video');

        // Update text submission button
        this.updateEndpointRateLimitUI('/observations/text', 'submitTextBtn', 'Submit Text');

        // Update query button
        this.updateEndpointRateLimitUI('/query', 'querySearchBtn', 'Search');

        // Update propositions load button
        this.updateEndpointRateLimitUI('/propositions', 'loadPropositions', 'Load Insights');
    }

    updateEndpointRateLimitUI(endpoint, buttonId, defaultText) {
        const fullEndpoint = `${this.apiBaseUrl}${endpoint}`;
        const rateLimitInfo = this.rateLimitInfo[fullEndpoint];
        const button = document.getElementById(buttonId);

        if (rateLimitInfo && button) {
            const remainingTime = Math.ceil((rateLimitInfo.resetTime - Date.now()) / 1000);

            if (remainingTime > 0) {
                button.disabled = true;
                button.textContent = `Wait ${remainingTime}s`;
                button.classList.add('rate-limited');

                // Add visual indicator
                this.addRateLimitIndicator(button, remainingTime, rateLimitInfo.limit, rateLimitInfo.remaining);
            } else {
                button.disabled = false;
                button.textContent = defaultText;
                button.classList.remove('rate-limited');
                this.removeRateLimitIndicator(button);
            }
        } else if (button) {
            button.disabled = false;
            button.textContent = defaultText;
            button.classList.remove('rate-limited');
            this.removeRateLimitIndicator(button);
        }
    }

    addRateLimitIndicator(button, remainingTime, limit, remaining) {
        // Remove existing indicator
        this.removeRateLimitIndicator(button);

        // Create indicator element
        const indicator = document.createElement('div');
        indicator.className = 'rate-limit-indicator';
        indicator.innerHTML = `
            <div class="rate-limit-progress">
                <div class="rate-limit-bar" style="width: ${((remaining || 0) / (limit || 1)) * 100}%"></div>
            </div>
            <div class="rate-limit-text">
                ${remaining || 0}/${limit || '∞'} remaining • ${remainingTime}s
            </div>
        `;

        // Insert after button
        button.parentNode.insertBefore(indicator, button.nextSibling);
    }

    removeRateLimitIndicator(button) {
        const indicator = button.parentNode.querySelector('.rate-limit-indicator');
        if (indicator) {
            indicator.remove();
        }
    }

    getRateLimitStatus(endpoint) {
        const fullEndpoint = `${this.apiBaseUrl}${endpoint}`;
        return this.rateLimitInfo[fullEndpoint] || null;
    }

    isRateLimited(endpoint) {
        const status = this.getRateLimitStatus(endpoint);
        return status && status.resetTime > Date.now();
    }

    /**
     * Initialize the application
     */
    async init() {
        this.applyTheme();
        this.setupEventListeners();
        this.setupTabNavigation();
        this.setupPropositionsListeners();
        this.setupTimelineListeners();
        this.setupNarrativeTimelineListeners();
        this.setupSuggestionsListeners();
        await this.checkConnection();
        this.updateConnectionStatus();

        // Initialize date inputs with today's date
        const today = new Date().toISOString().split('T')[0];
        document.getElementById('timelineDate').value = today;
        document.getElementById('narrativeTimelineDate').value = today;
    }

    /**
     * Apply theme to the application
     */
    applyTheme() {
        document.documentElement.setAttribute('data-theme', this.theme);
        const themeIcon = document.querySelector('#themeToggle i');
        if (themeIcon) {
            themeIcon.className = this.theme === 'dark' ? 'fas fa-sun' : 'fas fa-moon';
        }
    }

    /**
     * Toggle between light and dark themes
     */    toggleTheme() {
        this.theme = this.theme === 'light' ? 'dark' : 'light';
        localStorage.setItem('gum-theme', this.theme);
        this.applyTheme();
        this.showToast(`Switched to ${this.theme} mode`, 'info');
    }

    /**
     * Setup all event listeners
     */
    setupEventListeners() {
        // Theme toggle
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => this.toggleTheme());
        }



        // Action buttons
        const exportBtn = document.getElementById('exportBtn');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => this.exportResults());
        }

        const newAnalysisBtn = document.getElementById('newAnalysisBtn');
        if (newAnalysisBtn) {
            newAnalysisBtn.addEventListener('click', () => this.startNewAnalysis());
        }





        // Database cleanup button
        const cleanupDatabase = document.getElementById('cleanupDatabase');
        if (cleanupDatabase) {
            cleanupDatabase.addEventListener('click', () => this.handleDatabaseCleanup());
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                switch (e.key) {
                    case 'n':
                        e.preventDefault();
                        this.startNewAnalysis();
                        break;
                }
            }
        });


    }

















    /**
     * Simulate processing progress for better UX
     */
    async simulateProcessingProgress() {
        // Step 2: Processing
        for (let i = 0; i <= 100; i += 10) {
            this.updateProgressStep(2, i);
            await this.delay(200);
        }

        // Step 3: Analyzing
        for (let i = 0; i <= 100; i += 5) {
            this.updateProgressStep(3, i);
            await this.delay(150);
        }
    }

    /**
     * Poll job status for video processing
     */
    async pollJobStatus(jobId) {
        // Removed timeout limit - will poll indefinitely until completion or genuine error
        while (true) {
            try {
                const response = await fetch(`${this.apiBaseUrl}/observations/video/status/${jobId}`);

                if (response.ok) {
                    const status = await response.json();

                    // Update progress based on status
                    if (status.status === 'processing' || status.status === 'processing_frames') {
                        this.updateProgressStep(2, status.progress || 0);
                    } else if (status.status === 'analyzing') {
                        this.updateProgressStep(3, status.progress || 0);
                    }
                    if (status.status === 'completed') {
                        // Processing complete - now fetch insights
                        this.updateProgressStep(3, 100);
                        try {
                            const insightsResponse = await fetch(`${this.apiBaseUrl}/observations/video/${jobId}/insights`);
                            let insights = [];
                            let patterns = [];
                            let summary = '';

                            if (insightsResponse.ok) {
                                const insightsData = await insightsResponse.json();
                                insights = insightsData.key_insights || [];
                                patterns = insightsData.behavior_patterns || [];
                                summary = insightsData.summary || '';
                            }

                            return {
                                success: true,
                                frames_analyzed: status.total_frames || 0,
                                processing_time_ms: status.processing_time_ms || 0,
                                insights: insights,
                                patterns: patterns,
                                summary: summary,
                                analyses: status.frame_analyses || []
                            };
                        } catch (insightsError) {
                            console.warn('Failed to fetch insights:', insightsError);
                            // Return basic results without insights
                            return {
                                success: true,
                                frames_analyzed: status.total_frames || 0,
                                processing_time_ms: status.processing_time_ms || 0,
                                insights: ['Analysis completed successfully'],
                                patterns: ['Basic processing pattern identified'],
                                summary: 'Video analysis completed',
                                analyses: status.frame_analyses || []
                            };
                        }
                    } else if (status.status === 'error') {
                        throw new Error(status.error || 'Processing failed');
                    }
                } else {
                    throw new Error(`Status check failed: ${response.status}`);
                }

                // Wait before next poll
                await this.delay(2000);

            } catch (error) {
                throw new Error(`Status polling failed: ${error.message}`);
            }
        }
    }

    /**
     * Display analysis results
     */
    displayResults(results) {
        const resultsSection = document.getElementById('resultsSection');
        const resultsContent = document.getElementById('resultsContent');

        if (!resultsSection || !resultsContent) return;

        // Show results section
        resultsSection.style.display = 'block';

        // Create results HTML
        const resultsHtml = this.generateResultsHTML(results);
        resultsContent.innerHTML = resultsHtml;

        // Scroll to results
        resultsSection.scrollIntoView({ behavior: 'smooth' });

        // Store results for export
        this.currentResults = results;
    }

    /**
     * Generate results HTML
     */    generateResultsHTML(results) {
        return `
            <div class="results-grid">
                <div class="result-card">
                    <div class="result-header">
                        <h3><i class="fas fa-info-circle"></i> Analysis Summary</h3>
                    </div>
                    <div class="result-content">
                        <div class="summary-stats">
                            <div class="stat">
                                <span class="stat-label">Processing Time</span>
                                <span class="stat-value">${results.processing_time_ms?.toFixed(1) || 'N/A'}ms</span>
                            </div>
                            <div class="stat">
                                <span class="stat-label">Frames Analyzed</span>
                                <span class="stat-value">${results.frames_analyzed || 'N/A'}</span>
                            </div>
                            <div class="stat">
                                <span class="stat-label">Status</span>
                                <span class="stat-value success">Completed</span>
                            </div>
                        </div>
                        ${results.summary ? `<div class="summary-text"><p>${results.summary}</p></div>` : ''}
                    </div>
                </div>
                
                <div class="result-card">
                    <div class="result-header">
                        <h3><i class="fas fa-eye"></i> Key Insights</h3>
                    </div>
                    <div class="result-content">
                        <div class="insights-list">
                            ${this.generateInsightsList(results.insights || [])}
                        </div>
                    </div>
                </div>
                
                <div class="result-card">
                    <div class="result-header">
                        <h3><i class="fas fa-chart-line"></i> Behavior Patterns</h3>
                    </div>
                    <div class="result-content">
                        <div class="patterns-list">
                            ${this.generatePatternsList(results.patterns || [])}
                        </div>
                    </div>
                </div>
                
                <div class="result-card full-width">
                    <div class="result-header">
                        <h3><i class="fas fa-list"></i> Detailed Analysis</h3>
                    </div>
                    <div class="result-content">
                        <pre class="analysis-details">${JSON.stringify(results, null, 2)}</pre>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Generate insights list HTML
     */
    generateInsightsList(insights) {
        if (!insights.length) {
            return '<p class="no-data">No insights available</p>';
        }

        return insights.map(insight => `
            <div class="insight-item">
                <div class="insight-icon">
                    <i class="fas fa-lightbulb"></i>
                </div>
                <div class="insight-text">${insight}</div>
            </div>
        `).join('');
    }    /**
     * Generate patterns list HTML
     */
    generatePatternsList(patterns) {
        if (!patterns.length) {
            return '<p class="no-data">No patterns identified</p>';
        }

        return patterns.map(pattern => {
            // Handle both string patterns and object patterns
            if (typeof pattern === 'string') {
                return `
                    <div class="pattern-item">
                        <div class="pattern-name">${pattern}</div>
                    </div>
                `;
            } else {
                return `
                    <div class="pattern-item">
                        <div class="pattern-name">${pattern.name || 'Unknown Pattern'}</div>
                        <div class="pattern-confidence">
                            Confidence: ${((pattern.confidence || 0) * 100).toFixed(1)}%
                        </div>
                    </div>
                `;
            }
        }).join('');
    }

    /**
     * Export results
     */
    exportResults() {
        this.showToast('Export functionality is not available without upload feature', 'warning');
    }

    /**
     * Start new analysis
     */
    startNewAnalysis() {
        this.showToast('Upload feature has been removed from this interface', 'info');
    }

    /**
     * Handle database cleanup with confirmation
     */
    async handleDatabaseCleanup() {
        // Show confirmation dialog
        const confirmed = confirm(
            'Are you sure you want to clean the entire database?\n\n' +
            'This will permanently delete:\n' +
            '• All observations\n' +
            '• All propositions\n' +
            '• All insights\n' +
            '• All analysis data\n\n' +
            'This action cannot be undone!'
        );

        if (!confirmed) {
            return;
        }

        const cleanupBtn = document.getElementById('cleanupDatabase');
        if (cleanupBtn) {
            cleanupBtn.disabled = true;
            cleanupBtn.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i> Cleaning...';
        }

        try {
            const response = await fetch(`${this.apiBaseUrl}/database/cleanup`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to clean database');
            }

            const result = await response.json();

            // Show success message with deletion counts
            const message = `Database cleaned successfully!\n\n` +
                `Deleted:\n` +
                `• ${result.observations_deleted} observations\n` +
                `• ${result.propositions_deleted} propositions\n` +
                `• ${result.junction_records_deleted} junction records\n` +
                `• FTS indexes cleared`;

            this.showToast('Database cleaned successfully!', 'success');

            // Optional: Show detailed results in an alert
            alert(message);

            // Refresh any displayed data
            this.loadRecentHistory();

            // Reset any current results
            this.currentResults = null;
            const resultsSection = document.getElementById('resultsSection');
            if (resultsSection) {
                resultsSection.style.display = 'none';
            }

        } catch (error) {
            console.error('Database cleanup failed:', error);
            this.showToast(`Database cleanup failed: ${error.message}`, 'error');
        } finally {
            // Restore button state
            if (cleanupBtn) {
                cleanupBtn.disabled = false;
                cleanupBtn.innerHTML = '<i class="fas fa-trash" aria-hidden="true"></i> Clean Database';
            }
        }
    }

    /**
     * Hide progress section
     */
    hideProgressSection() {
        const progressSection = document.getElementById('progressSection');
        if (progressSection) {
            progressSection.style.display = 'none';
        }
    }

    /**
     * Disable form during upload
     */
    disableForm() {
        const form = document.getElementById('videoForm');
        if (form) {
            const inputs = form.querySelectorAll('input, button, select');
            inputs.forEach(input => input.disabled = true);
        }
    }

    /**
     * Enable form after upload
     */
    enableForm() {
        const form = document.getElementById('videoForm');
        if (form) {
            const inputs = form.querySelectorAll('input, button, select');
            inputs.forEach(input => input.disabled = false);
        }

        // Keep upload button disabled if no file selected
        if (!this.selectedFile) {
            this.disableUploadButton();
        }
    }



    /**
     * Check API connection
     */
    async checkConnection() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/health`, {
                timeout: 5000
            });

            if (response.ok) {
                const health = await response.json();
                this.connectionStatus = health.gum_connected ? 'connected' : 'disconnected';
            } else {
                this.connectionStatus = 'disconnected';
            }
        } catch (error) {
            this.connectionStatus = 'disconnected';
        }
    }

    /**
     * Update connection status display
     */
    updateConnectionStatus() {
        const statusElement = document.getElementById('connectionStatus');
        if (!statusElement) return;

        const statusText = {
            'connected': 'Connected',
            'disconnected': 'Disconnected',
            'connecting': 'Connecting...'
        };

        // Hide the connection status when connected, only show when there are issues
        if (this.connectionStatus === 'connected') {
            statusElement.style.display = 'none';
        } else {
            statusElement.style.display = 'flex';
            statusElement.className = `connection-status ${this.connectionStatus}`;
            const span = statusElement.querySelector('span');
            if (span) {
                span.textContent = statusText[this.connectionStatus];
            }
        }

        // Show warning if disconnected
        if (this.connectionStatus === 'disconnected') {
            this.showToast('Cannot connect to analysis service. Please check if the controller is running.', 'error');
        }
    }

    /**
     * Update scroll progress
     */
    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        if (!toast) return;

        // Clear any existing timeout
        if (this.toastTimeout) {
            clearTimeout(this.toastTimeout);
        }

        // Get icon for toast type
        const icons = {
            success: 'fas fa-check-circle',
            error: 'fas fa-exclamation-circle',
            warning: 'fas fa-exclamation-triangle',
            info: 'fas fa-info-circle'
        };

        // Set toast content with icon
        toast.innerHTML = `
            <i class="${icons[type] || icons.info}" aria-hidden="true"></i>
            <span>${message}</span>
        `;

        toast.className = `toast ${type} show`;

        // Auto hide after 6 seconds (longer for better readability)
        this.toastTimeout = setTimeout(() => {
            toast.classList.remove('show');
        }, 6000);
    }

    /**
     * Utility: Format file size
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';

        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));

        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    /**
     * Utility: Format duration
     */
    formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);

        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        } else {
            return `${minutes}:${secs.toString().padStart(2, '0')}`;
        }
    }

    /**
     * Utility: Delay function
     */
    delay(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    // ========================================
    // TEXT SHIMMER LOADING ANIMATION
    // ========================================

    /**
     * Create a text shimmer element
     * @param {string} text - The text to display
     * @param {Object} options - Configuration options
     * @param {string} options.element - HTML element type (default: 'span')
     * @param {string} options.className - Additional CSS classes
     * @param {number} options.duration - Animation duration in seconds (default: 2)
     * @param {number} options.spread - Spread of the shimmer effect (default: 2)
     * @param {string} options.color - Color variant ('blue', 'cyan', or default)
     * @param {string} options.size - Size variant ('sm', 'lg', 'xl', or default)
     * @param {boolean} options.mono - Use monospace font
     * @param {boolean} options.fast - Use fast animation
     * @param {boolean} options.slow - Use slow animation
     * @returns {HTMLElement} The shimmer element
     */
    createTextShimmer(text, options = {}) {
        const {
            element = 'span',
            className = '',
            duration = 2,
            spread = 2,
            color = '',
            size = '',
            mono = false,
            fast = false,
            slow = false
        } = options;

        // Create the element
        const shimmerElement = document.createElement(element);
        shimmerElement.textContent = text;
        shimmerElement.className = 'text-shimmer';

        // Add color variant
        if (color === 'blue') {
            shimmerElement.classList.add('text-shimmer-blue');
        } else if (color === 'cyan') {
            shimmerElement.classList.add('text-shimmer-cyan');
        }

        // Add size variant
        if (size === 'sm') {
            shimmerElement.classList.add('text-shimmer-sm');
        } else if (size === 'lg') {
            shimmerElement.classList.add('text-shimmer-lg');
        } else if (size === 'xl') {
            shimmerElement.classList.add('text-shimmer-xl');
        }

        // Add font variant
        if (mono) {
            shimmerElement.classList.add('text-shimmer-mono');
        }

        // Add duration variant
        if (fast) {
            shimmerElement.classList.add('text-shimmer-fast');
        } else if (slow) {
            shimmerElement.classList.add('text-shimmer-slow');
        }

        // Add custom classes
        if (className) {
            shimmerElement.classList.add(...className.split(' '));
        }

        // Set custom duration if provided
        if (duration !== 2) {
            shimmerElement.style.animationDuration = `${duration}s`;
        }

        // Set custom spread if provided
        if (spread !== 2) {
            const dynamicSpread = text.length * spread;
            shimmerElement.style.setProperty('--spread', `${dynamicSpread}px`);
        }

        return shimmerElement;
    }

    /**
     * Show loading state with text shimmer
     * @param {string|HTMLElement} target - Target element or selector
     * @param {string} loadingText - Text to show while loading
     * @param {Object} options - Shimmer options
     * @returns {string} Original content for restoration
     */
    showLoadingShimmer(target, loadingText = 'Loading...', options = {}) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) return null;

        // Store original content
        const originalContent = element.innerHTML;
        const originalText = element.textContent;

        // Create shimmer element
        const shimmerElement = this.createTextShimmer(loadingText, options);

        // Clear and add shimmer
        element.innerHTML = '';
        element.appendChild(shimmerElement);

        // Store for restoration
        const instanceId = `shimmer_${Date.now()}_${Math.random()}`;
        this.textShimmerInstances.set(instanceId, {
            element: element,
            originalContent: originalContent,
            originalText: originalText,
            shimmerElement: shimmerElement
        });

        return instanceId;
    }

    /**
     * Hide loading shimmer and restore original content
     * @param {string} instanceId - Instance ID returned from showLoadingShimmer
     */
    hideLoadingShimmer(instanceId) {
        const instance = this.textShimmerInstances.get(instanceId);
        if (!instance) return;

        const { element, originalContent } = instance;

        // Restore original content
        element.innerHTML = originalContent;

        // Clean up
        this.textShimmerInstances.delete(instanceId);
    }

    /**
     * Show loading state for a button
     * @param {string|HTMLElement} button - Button element or selector
     * @param {string} loadingText - Text to show while loading
     * @param {Object} options - Shimmer options
     * @returns {string} Instance ID for restoration
     */
    showButtonLoading(button, loadingText = 'Loading...', options = {}) {
        const buttonElement = typeof button === 'string' ? document.querySelector(button) : button;
        if (!buttonElement) return null;

        // Store original state
        const originalText = buttonElement.textContent;
        const originalDisabled = buttonElement.disabled;

        // Disable button
        buttonElement.disabled = true;
        buttonElement.classList.add('loading');

        // Create shimmer with button-specific options
        const shimmerOptions = {
            ...options,
            className: 'btn-shimmer'
        };

        const shimmerElement = this.createTextShimmer(loadingText, shimmerOptions);

        // Clear and add shimmer
        buttonElement.innerHTML = '';
        buttonElement.appendChild(shimmerElement);

        // Store for restoration
        const instanceId = `button_shimmer_${Date.now()}_${Math.random()}`;
        this.textShimmerInstances.set(instanceId, {
            element: buttonElement,
            originalText: originalText,
            originalDisabled: originalDisabled,
            shimmerElement: shimmerElement,
            type: 'button'
        });

        return instanceId;
    }

    /**
     * Hide button loading state
     * @param {string} instanceId - Instance ID returned from showButtonLoading
     */
    hideButtonLoading(instanceId) {
        const instance = this.textShimmerInstances.get(instanceId);
        if (!instance || instance.type !== 'button') return;

        const { element, originalText, originalDisabled } = instance;

        // Restore original state
        element.textContent = originalText;
        element.disabled = originalDisabled;
        element.classList.remove('loading');

        // Clean up
        this.textShimmerInstances.delete(instanceId);
    }

    /**
     * Show loading state for a card or container
     * @param {string|HTMLElement} target - Target element or selector
     * @param {string} loadingText - Text to show while loading
     * @param {Object} options - Shimmer options
     * @returns {string} Instance ID for restoration
     */
    showCardLoading(target, loadingText = 'Loading data...', options = {}) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) return null;

        // Store original content
        const originalContent = element.innerHTML;

        // Add loading class
        element.classList.add('card-loading');

        // Create loading container
        const loadingContainer = document.createElement('div');
        loadingContainer.className = 'loading-container';
        loadingContainer.style.cssText = `
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: var(--spacing-xxl);
            text-align: center;
        `;

        // Add spinner
        const spinner = document.createElement('div');
        spinner.className = 'spinner';
        loadingContainer.appendChild(spinner);

        // Add shimmer text
        const shimmerElement = this.createTextShimmer(loadingText, {
            ...options,
            className: 'mt-3'
        });
        loadingContainer.appendChild(shimmerElement);

        // Replace content
        element.innerHTML = '';
        element.appendChild(loadingContainer);

        // Store for restoration
        const instanceId = `card_shimmer_${Date.now()}_${Math.random()}`;
        this.textShimmerInstances.set(instanceId, {
            element: element,
            originalContent: originalContent,
            shimmerElement: shimmerElement,
            type: 'card'
        });

        return instanceId;
    }

    /**
     * Hide card loading state
     * @param {string} instanceId - Instance ID returned from showCardLoading
     */
    hideCardLoading(instanceId) {
        const instance = this.textShimmerInstances.get(instanceId);
        if (!instance || instance.type !== 'card') return;

        const { element, originalContent } = instance;

        // Restore original content
        element.innerHTML = originalContent;
        element.classList.remove('card-loading');

        // Clean up
        this.textShimmerInstances.delete(instanceId);
    }

    // ===== PROPOSITIONS FUNCTIONALITY =====

    /**
     * Setup propositions event listeners
     */
    setupPropositionsListeners() {
        const loadPropositionsBtn = document.getElementById('loadPropositions');
        const confidenceFilter = document.getElementById('confidenceFilter');
        const sortBySelect = document.getElementById('sortBy');
        const prevBtn = document.getElementById('prevPropositions');
        const nextBtn = document.getElementById('nextPropositions');

        if (loadPropositionsBtn) {
            loadPropositionsBtn.addEventListener('click', () => {
                this.currentPropositionsPage = 1;
                this.loadPropositions();
            });
        }

        if (confidenceFilter) {
            confidenceFilter.addEventListener('change', () => {
                this.currentPropositionsPage = 1;
                this.loadPropositions();
            });
        }

        if (sortBySelect) {
            sortBySelect.addEventListener('change', () => {
                this.currentPropositionsPage = 1;
                this.loadPropositions();
            });
        }

        if (prevBtn) {
            prevBtn.addEventListener('click', () => {
                if (this.currentPropositionsPage > 1) {
                    this.currentPropositionsPage--;
                    this.loadPropositions();
                }
            });
        }

        if (nextBtn) {
            nextBtn.addEventListener('click', () => {
                this.currentPropositionsPage++;
                this.loadPropositions();
            });
        }
    }

    /**
     * Load propositions from the API
     */
    async loadPropositions() {
        const loadBtn = document.getElementById('loadPropositions');
        const contentContainer = document.getElementById('propositionsContent');
        const statsContainer = document.getElementById('propositionsStats');
        const paginationContainer = document.getElementById('propositionsPagination');

        if (!contentContainer) return;

        try {
            // Show loading state with text shimmer
            let buttonLoadingInstanceId = null;
            if (loadBtn) {
                buttonLoadingInstanceId = this.showButtonLoading(loadBtn, 'Loading insights...', {
                    color: 'cyan',
                    fast: true
                });
            }

            // Show card loading state
            const cardLoadingInstanceId = this.showCardLoading(contentContainer, 'Loading insights...', {
                color: 'cyan',
                size: 'lg'
            });

            // Get filter values
            const confidenceMin = document.getElementById('confidenceFilter')?.value || null;
            const sortBy = document.getElementById('sortBy')?.value || 'created_at';
            const limit = 20;
            const offset = (this.currentPropositionsPage - 1) * limit;

            // Build query parameters
            const params = new URLSearchParams({
                limit: limit.toString(),
                offset: offset.toString(),
                sort_by: sortBy
            });

            if (confidenceMin) {
                params.append('confidence_min', confidenceMin);
            }

            // Fetch propositions
            const response = await fetch(`${this.apiBaseUrl}/propositions?${params}`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const propositions = await response.json();

            // Fetch count for stats
            const countParams = new URLSearchParams();
            if (confidenceMin) {
                countParams.append('confidence_min', confidenceMin);
            }

            const countResponse = await fetch(`${this.apiBaseUrl}/propositions/count?${countParams}`);
            const countData = await countResponse.json();

            // Hide loading states
            if (buttonLoadingInstanceId) {
                this.hideButtonLoading(buttonLoadingInstanceId);
            }
            this.hideCardLoading(cardLoadingInstanceId);

            // Display results
            this.displayPropositions(propositions, countData);
            this.updatePropositionsPagination(propositions.length, limit);

            this.showToast(`Loaded ${propositions.length} insights`, 'success');

        } catch (error) {
            console.error('Error loading propositions:', error);
            this.showToast(`Failed to load insights: ${error.message}`, 'error');
            this.displayEmptyPropositions();
        }
    }

    /**
     * Display propositions in the UI
     */
    displayPropositions(propositions, countData) {
        const contentContainer = document.getElementById('propositionsContent');
        const statsContainer = document.getElementById('propositionsStats');

        if (!contentContainer) return;

        // Show stats
        if (statsContainer && countData) {
            statsContainer.style.display = 'flex';
            statsContainer.innerHTML = `
                <div class="stat-item">
                    <i class="fas fa-lightbulb"></i>
                    <span>Total: ${countData.total_propositions} insights</span>
                </div>
                <div class="stat-item">
                    <i class="fas fa-filter"></i>
                    <span>Showing: ${propositions.length} results</span>
                </div>
                ${countData.confidence_filter ? `
                    <div class="stat-item">
                        <i class="fas fa-star"></i>
                        <span>Min confidence: ${countData.confidence_filter}</span>
                    </div>
                ` : ''}
            `;
        }

        // Display propositions
        if (propositions.length === 0) {
            this.displayEmptyPropositions();
            return;
        }

        contentContainer.innerHTML = propositions.map((prop, index) =>
            this.createPropositionCard(prop, index)
        ).join('');
    }

    /**
     * Create a proposition card HTML
     */
    createPropositionCard(proposition, index) {
        const confidence = proposition.confidence;
        const confidenceClass = this.getConfidenceClass(confidence);
        const confidenceLabel = this.getConfidenceLabel(confidence);

        const createdDate = new Date(proposition.created_at);
        const formattedDate = createdDate.toLocaleDateString() + ' ' +
            this.formatLocalTime(proposition.created_at);

        return `
            <div class="proposition-card" style="animation-delay: ${index * 0.1}s">
                <div class="proposition-header">
                    <div class="proposition-meta">
                        <span class="proposition-id">#${proposition.id}</span>
                        <span class="confidence-badge ${confidenceClass}">
                            <i class="fas fa-star"></i>
                            ${confidenceLabel}
                        </span>
                    </div>
                </div>
                
                <div class="proposition-text">
                    ${this.escapeHtml(proposition.text)}
                </div>
                
                ${proposition.reasoning ? `
                    <div class="proposition-reasoning">
                        <strong>Reasoning:</strong> ${this.escapeHtml(proposition.reasoning)}
                    </div>
                ` : ''}
                
                <div class="proposition-footer">
                    <div class="proposition-date">
                        <i class="fas fa-clock"></i>
                        <span>${formattedDate}</span>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Get confidence CSS class
     */
    getConfidenceClass(confidence) {
        if (!confidence) return 'confidence-none';
        if (confidence >= 8) return 'confidence-high';
        if (confidence >= 6) return 'confidence-medium';
        return 'confidence-low';
    }

    /**
     * Get confidence label
     */
    getConfidenceLabel(confidence) {
        if (!confidence) return 'No confidence';
        return `${confidence}/10`;
    }

    /**
     * Display empty state for propositions
     */
    displayEmptyPropositions() {
        const contentContainer = document.getElementById('propositionsContent');
        const statsContainer = document.getElementById('propositionsStats');

        if (statsContainer) {
            statsContainer.style.display = 'none';
        }

        if (contentContainer) {
            contentContainer.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-lightbulb"></i>
                    <h3>No insights found</h3>
                    <p>No propositions match your current filters. Try adjusting the confidence level or submit more observations.</p>
                </div>
            `;
        }
    }

    /**
     * Update pagination controls
     */
    updatePropositionsPagination(resultCount, limit) {
        const paginationContainer = document.getElementById('propositionsPagination');
        const prevBtn = document.getElementById('prevPropositions');
        const nextBtn = document.getElementById('nextPropositions');
        const pageInfo = document.getElementById('propositionsPageInfo');

        if (!paginationContainer) return;

        // Show pagination if we have results
        if (resultCount > 0) {
            paginationContainer.style.display = 'flex';

            // Update page info
            if (pageInfo) {
                pageInfo.textContent = `Page ${this.currentPropositionsPage}`;
            }

            // Update button states
            if (prevBtn) {
                prevBtn.disabled = this.currentPropositionsPage <= 1;
            }

            if (nextBtn) {
                nextBtn.disabled = resultCount < limit;
            }
        } else {
            paginationContainer.style.display = 'none';
        }
    }

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ===== TAB NAVIGATION FUNCTIONALITY =====

    /**
     * Setup tab navigation event listeners
     */
    setupTabNavigation() {
        const tabButtons = document.querySelectorAll('.tab-button');

        tabButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                const tabId = button.getAttribute('data-tab');
                this.switchTab(tabId);
            });
        });

        // Initially hide sidebar since home tab is active by default
        const sidebar = document.querySelector('.tabs-navigation');
        if (sidebar) {
            sidebar.style.display = 'none';
        }

        // Ensure top-nav layout is disabled on initial Home
        const main = document.querySelector('.main-content');
        if (main) {
            main.classList.remove('has-top-nav');
        }
    }

    /**
     * Switch to a specific tab
     */
    switchTab(tabName) {
        // Clean up previous tab
        if (this.activeTab === 'suggestions') {
            this.stopSuggestionPolling();
        }

        // Hide all tab panels
        const tabPanels = document.querySelectorAll('.tab-panel');
        tabPanels.forEach(panel => {
            panel.classList.remove('active');
        });

        // Remove active class from all tab buttons
        const tabButtons = document.querySelectorAll('.tab-button');
        tabButtons.forEach(button => {
            button.classList.remove('active');
        });

        // Show the selected tab panel
        const selectedPanel = document.getElementById(`${tabName}-panel`);
        if (selectedPanel) {
            selectedPanel.classList.add('active');
        }

        // Add active class to the selected tab button
        const selectedButton = document.querySelector(`[data-tab="${tabName}"]`);
        if (selectedButton) {
            selectedButton.classList.add('active');
        }

        // Handle sidebar visibility
        const sidebar = document.querySelector('.tabs-navigation');
        if (sidebar) {
            if (tabName === 'home') {
                sidebar.style.display = 'none';
            } else {
                sidebar.style.display = 'block';
            }
        }

        // Toggle top-nav layout only where sidebar used to show (non-Home tabs)
        const main = document.querySelector('.main-content');
        if (main) {
            if (tabName === 'home') {
                main.classList.remove('has-top-nav');
            } else {
                main.classList.add('has-top-nav');
            }
        }

        // Load content based on tab
        switch (tabName) {
            case 'insights':
                this.loadPropositions();
                break;
            case 'timeline':
                this.loadTimeline();
                break;
            case 'narrative':
                this.loadNarrativeTimeline();
                break;
            case 'suggestions':
                // Initialize real-time suggestion stream
                this.initializeSuggestionStream();
                break;
            // 'dashboard' tab removed; Home CTA routes to 'timeline'
        }
    }



    // ===== TIMELINE FUNCTIONALITY =====

    /**
     * Setup timeline event listeners
     */
    setupTimelineListeners() {
        const loadTimelineBtn = document.getElementById('loadTimeline');
        const timelineDateInput = document.getElementById('timelineDate');
        const timelineConfidenceFilter = document.getElementById('timelineConfidenceFilter');

        if (loadTimelineBtn) {
            loadTimelineBtn.addEventListener('click', () => this.loadTimeline());
        }

        if (timelineDateInput) {
            // Set default date to today
            const today = new Date().toISOString().split('T')[0];
            timelineDateInput.value = today;
        }

        if (timelineConfidenceFilter) {
            timelineConfidenceFilter.addEventListener('change', () => {
                // Auto-reload timeline when filter changes
                if (document.getElementById('timeline-panel').classList.contains('active')) {
                    this.loadTimeline();
                }
            });
        }
    }

    /**
     * Load timeline data for the selected date
     */
    async loadTimeline() {
        const loadBtn = document.getElementById('loadTimeline');
        const contentContainer = document.getElementById('timelineContent');
        const dateInput = document.getElementById('timelineDate');
        const confidenceFilter = document.getElementById('timelineConfidenceFilter');

        if (!contentContainer || !dateInput) return;

        try {
            // Show loading state with text shimmer
            let buttonLoadingInstanceId = null;
            if (loadBtn) {
                buttonLoadingInstanceId = this.showButtonLoading(loadBtn, 'Loading timeline...', {
                    color: 'cyan',
                    fast: true
                });
            }

            // Show card loading state
            const cardLoadingInstanceId = this.showCardLoading(contentContainer, 'Loading timeline...', {
                color: 'cyan',
                size: 'lg'
            });

            // Get filter values
            const date = dateInput.value;
            const confidenceMin = confidenceFilter?.value || null;

            // Build query parameters
            const params = new URLSearchParams({
                date: date
            });

            if (confidenceMin) {
                params.append('confidence_min', confidenceMin);
            }

            // Fetch timeline data
            const response = await fetch(`${this.apiBaseUrl}/propositions/by-hour?${params}`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const timelineData = await response.json();

            // Hide loading states
            if (buttonLoadingInstanceId) {
                this.hideButtonLoading(buttonLoadingInstanceId);
            }
            this.hideCardLoading(cardLoadingInstanceId);

            // Display results
            this.displayTimeline(timelineData);

            this.showToast(`Loaded timeline for ${date}`, 'success');

        } catch (error) {
            console.error('Error loading timeline:', error);
            this.showToast(`Failed to load timeline: ${error.message}`, 'error');
            this.displayEmptyTimeline();
        }
    }

    /**
     * Display timeline data in the UI
     */
    displayTimeline(timelineData) {
        const contentContainer = document.getElementById('timelineContent');

        if (!contentContainer) return;

        if (!timelineData.hourly_groups || timelineData.hourly_groups.length === 0) {
            this.displayEmptyTimeline();
            return;
        }

        // Format date for display - ensure proper timezone handling
        let displayDate;
        try {
            // timelineData.date is in format "2025-08-08" (date only)
            // We need to create a proper date object for the user's local timezone
            const [year, month, day] = timelineData.date.split('-').map(Number);
            // Create date using UTC to avoid timezone conversion issues
            const localDate = new Date(Date.UTC(year, month - 1, day, 12, 0, 0)); // month is 0-indexed, noon UTC

            displayDate = localDate.toLocaleDateString('en-US', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        } catch (error) {
            console.error('Error formatting date:', error);
            displayDate = 'Invalid Date';
        }

        contentContainer.innerHTML = `
            <div class="timeline-date-header">
                <h3 class="timeline-date-title">
                    <i class="fas fa-calendar"></i>
                    ${displayDate}
                </h3>
                <div class="timeline-stats">
                    <div class="timeline-stat">
                        <i class="fas fa-clock"></i>
                        <span>${timelineData.total_hours} ${timelineData.total_hours === 1 ? 'hour' : 'hours'}</span>
                    </div>
                    <div class="timeline-stat">
                        <i class="fas fa-lightbulb"></i>
                        <span>${timelineData.total_propositions} ${timelineData.total_propositions === 1 ? 'insight' : 'insights'}</span>
                    </div>
                </div>
            </div>
            <div class="timeline-hours">
                ${timelineData.hourly_groups.map((hourGroup, index) =>
            this.createTimelineHourItem(hourGroup, index)
        ).join('')}
            </div>
        `;

        // Setup click handlers for hour items
        this.setupTimelineHourHandlers();
    }

    /**
     * Create a timeline hour item HTML
     */
    createTimelineHourItem(hourGroup, index) {
        const hour = hourGroup.hour;
        const hourDisplay = hourGroup.hour_display;
        const count = hourGroup.proposition_count;
        const propositions = Array.isArray(hourGroup.propositions) ? [...hourGroup.propositions] : [];

        // Sort propositions by created_at ascending (unknowns last)
        propositions.sort((a, b) => {
            const aTime = a?.created_at ? new Date(a.created_at).getTime() : Infinity;
            const bTime = b?.created_at ? new Date(b.created_at).getTime() : Infinity;
            return aTime - bTime;
        });

        return `
            <div class="timeline-hour-item" data-hour="${hour}" style="animation-delay: ${index * 0.1}s">
                <div class="timeline-hour-left">
                    <div class="timeline-hour-bullet"></div>
                    <div class="timeline-hour-time">${hourDisplay}</div>
                    <div class="timeline-hour-count">${count} insights</div>
                </div>
                <button class="timeline-hour-button" data-hour="${hour}">
                    Click Insights
                </button>
                <div class="timeline-hour-details" id="timeline-hour-${hour}">
                    <div class="timeline-propositions">
                        <strong>Individual Insights:</strong>
                        ${propositions.map(prop => {
            const timeLabel = prop?.created_at ? this.formatLocalTime(prop.created_at) : 'Unknown time';
            return `
                                <div class="timeline-proposition">
                                    <span class="timeline-proposition-time">${timeLabel}</span>
                                    <div class="timeline-proposition-text">
                                        <strong>#${prop.id}</strong> (Confidence: ${prop.confidence || 'N/A'}) - ${this.escapeHtml(prop.text)}
                                    </div>
                                </div>
                            `;
        }).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Setup click handlers for timeline hour items
     */
    setupTimelineHourHandlers() {
        const hourItems = document.querySelectorAll('.timeline-hour-item');
        const hourButtons = document.querySelectorAll('.timeline-hour-button');

        hourItems.forEach(item => {
            item.addEventListener('click', (e) => {
                // Don't trigger if clicking on the button
                if (e.target.classList.contains('timeline-hour-button')) {
                    return;
                }

                const hour = item.getAttribute('data-hour');
                this.toggleTimelineHourDetails(hour);
            });
        });

        hourButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                e.stopPropagation(); // Prevent item click
                const hour = button.getAttribute('data-hour');
                this.toggleTimelineHourDetails(hour);
            });
        });
    }

    /**
     * Toggle timeline hour details visibility
     */
    toggleTimelineHourDetails(hour) {
        const detailsElement = document.getElementById(`timeline-hour-${hour}`);
        const button = document.querySelector(`[data-hour="${hour}"].timeline-hour-button`);

        if (!detailsElement) return;

        const isVisible = detailsElement.classList.contains('show');

        if (isVisible) {
            detailsElement.classList.remove('show');
            if (button) {
                button.textContent = 'Click Insights';
            }
        } else {
            detailsElement.classList.add('show');
            if (button) {
                button.textContent = 'Hide Insights';
            }
        }
    }

    /**
     * Display empty timeline state
     */
    displayEmptyTimeline() {
        const contentContainer = document.getElementById('timelineContent');

        if (!contentContainer) return;

        contentContainer.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-clock" aria-hidden="true"></i>
                <h3>No timeline data</h3>
                <p>No insights found for the selected date. Try a different date or check if you have any observations recorded.</p>
            </div>
        `;
    }

    /**
     * Setup narrative timeline event listeners
     */
    setupNarrativeTimelineListeners() {
        const loadNarrativeTimelineBtn = document.getElementById('loadNarrativeTimeline');
        const narrativeTimelineDateInput = document.getElementById('narrativeTimelineDate');

        if (loadNarrativeTimelineBtn) {
            loadNarrativeTimelineBtn.addEventListener('click', () => this.loadNarrativeTimeline());
        }

        if (narrativeTimelineDateInput) {
            // Set default date to today
            const today = new Date().toISOString().split('T')[0];
            narrativeTimelineDateInput.value = today;
        }
    }

    setupSuggestionsListeners() {
        // SSE-based suggestion system - no manual generation needed
        // The system automatically generates suggestions when high-confidence insights are detected

        // Set up cleanup for polling on page unload
        window.addEventListener('beforeunload', () => {
            this.stopSuggestionPolling();
            if (this.suggestionEventSource) {
                this.suggestionEventSource.close();
                console.log('SSE connection closed on page unload');
            }
        });
    }

    /**
     * Load narrative timeline data
     */
    async loadNarrativeTimeline() {
        const loadBtn = document.getElementById('loadNarrativeTimeline');
        const contentContainer = document.getElementById('narrativeTimelineContent');
        const dateInput = document.getElementById('narrativeTimelineDate');

        if (!contentContainer || !dateInput) return;

        try {
            // Show loading state with text shimmer
            let buttonLoadingInstanceId = null;
            if (loadBtn) {
                buttonLoadingInstanceId = this.showButtonLoading(loadBtn, 'Loading timeline...', {
                    color: 'cyan',
                    fast: true
                });
            }

            // Show card loading state
            const cardLoadingInstanceId = this.showCardLoading(contentContainer, 'Loading narrative timeline...', {
                color: 'cyan',
                size: 'lg'
            });

            // Get date value
            const date = dateInput.value;

            // Fetch narrative timeline data
            const response = await fetch(`${this.apiBaseUrl}/observations/by-hour?date=${date}`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const timelineData = await response.json();

            // Hide loading states
            if (buttonLoadingInstanceId) {
                this.hideButtonLoading(buttonLoadingInstanceId);
            }
            this.hideCardLoading(cardLoadingInstanceId);

            // Display results
            this.displayNarrativeTimeline(timelineData);

            this.showToast(`Loaded narrative timeline for ${date}`, 'success');

        } catch (error) {
            console.error('Error loading narrative timeline:', error);
            this.showToast(`Failed to load narrative timeline: ${error.message}`, 'error');
            this.displayEmptyNarrativeTimeline();
        }
    }

    /**
     * Display narrative timeline data in the UI
     */
    displayNarrativeTimeline(timelineData) {
        const contentContainer = document.getElementById('narrativeTimelineContent');

        if (!contentContainer) return;

        if (!timelineData.hourly_groups || timelineData.hourly_groups.length === 0) {
            this.displayEmptyNarrativeTimeline();
            return;
        }

        // Format date for display - ensure proper timezone handling
        let displayDate;
        try {
            // timelineData.date is in format "2025-08-08" (date only)
            // We need to create a proper date object for the user's local timezone
            const [year, month, day] = timelineData.date.split('-').map(Number);
            // Create date using UTC to avoid timezone conversion issues
            const localDate = new Date(Date.UTC(year, month - 1, day, 12, 0, 0)); // month is 0-indexed, noon UTC

            displayDate = localDate.toLocaleDateString('en-US', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        } catch (error) {
            console.error('Error formatting narrative timeline date:', error);
            displayDate = 'Invalid Date';
        }

        contentContainer.innerHTML = `
            <div class="narrative-timeline-date-header">
                <h3 class="narrative-timeline-date-title">
                    <i class="fas fa-calendar"></i>
                    ${displayDate}
                </h3>
                <div class="narrative-timeline-stats">
                    <div class="narrative-timeline-stat">
                        <i class="fas fa-clock"></i>
                        <span>${timelineData.total_hours} ${timelineData.total_hours === 1 ? 'hour' : 'hours'}</span>
                    </div>
                    <div class="narrative-timeline-stat">
                        <i class="fas fa-list-alt"></i>
                        <span>${timelineData.total_observations} ${timelineData.total_observations === 1 ? 'activity' : 'activities'}</span>
                    </div>
                    <div class="narrative-timeline-stat">
                        <i class="fas fa-globe"></i>
                        <span>${this.getCurrentTimezone()}</span>
                    </div>
                </div>
            </div>
            <div class="narrative-timeline-hours">
                ${timelineData.hourly_groups.map((hourGroup, index) =>
            this.createNarrativeTimelineHourItem(hourGroup, index)
        ).join('')}
            </div>
        `;

        // Setup click handlers for expandable hours
        this.setupNarrativeTimelineHourHandlers();
    }

    /**
     * Clean up raw transcription data for better readability
     */
    cleanTranscriptionData(content) {
        if (!content) return '';

        let cleaned = content;

        // Remove technical headers and metadata
        cleaned = cleaned.replace(/```plaintext\s*/g, '');
        cleaned = cleaned.replace(/```\s*$/g, '');
        cleaned = cleaned.replace(/Application:\s*/g, '');
        cleaned = cleaned.replace(/Window Title:\s*/g, '');
        cleaned = cleaned.replace(/File Path:\s*/g, '');
        cleaned = cleaned.replace(/URL:\s*/g, '');
        cleaned = cleaned.replace(/Timestamp:\s*/g, '');
        cleaned = cleaned.replace(/Date:\s*/g, '');

        // Remove file listings and technical details
        cleaned = cleaned.replace(/File Explorer:\s*[-•]\s*[^\n]+\n/g, '');
        cleaned = cleaned.replace(/[-•]\s*[^\n]+\.(py|md|txt|json|yaml|yml|toml|lock|gitignore|license|readme)/gi, '');
        cleaned = cleaned.replace(/[-•]\s*__pycache__\//g, '');
        cleaned = cleaned.replace(/[-•]\s*\.git\//g, '');
        cleaned = cleaned.replace(/[-•]\s*\.vscode\//g, '');

        // Remove terminal output and logs
        cleaned = cleaned.replace(/Terminal Output:\s*/g, '');
        cleaned = cleaned.replace(/PS C:[^>]*>/g, '');
        cleaned = cleaned.replace(/\d{2}:\d{2}:\d{2}\s*\[Screen\]\s*[^\n]*/g, '');
        cleaned = cleaned.replace(/INFO:[^:]*:\s*[^\n]*/g, '');
        cleaned = cleaned.replace(/DEBUG:[^:]*:\s*[^\n]*/g, '');
        cleaned = cleaned.replace(/WARNING:[^:]*:\s*[^\n]*/g, '');
        cleaned = cleaned.replace(/ERROR:[^:]*:\s*[^\n]*/g, '');

        // Remove markdown formatting
        cleaned = cleaned.replace(/#{1,6}\s*/g, '');
        cleaned = cleaned.replace(/\*\*([^*]+)\*\*/g, '$1');
        cleaned = cleaned.replace(/\*([^*]+)\*/g, '$1');
        cleaned = cleaned.replace(/`([^`]+)`/g, '$1');

        // Remove code blocks
        cleaned = cleaned.replace(/```bash\s*[^`]*```/g, '');
        cleaned = cleaned.replace(/```\s*[^`]*```/g, '');

        // Clean up application names
        cleaned = cleaned.replace(/Application:\s*([^\n]+)/g, 'Using $1');
        cleaned = cleaned.replace(/Title:\s*([^\n]+)/g, 'Viewing: $1');

        // Extract meaningful content
        const lines = cleaned.split('\n').filter(line => {
            const trimmed = line.trim();
            return trimmed.length > 0 &&
                !trimmed.match(/^[-•\s]*$/) &&
                !trimmed.match(/^[A-Z][a-z]+:\s*$/) &&
                !trimmed.match(/^\d{2}:\d{2}:\d{2}/) &&
                !trimmed.match(/^PS C:/) &&
                !trimmed.match(/^INFO:/) &&
                !trimmed.match(/^DEBUG:/) &&
                !trimmed.match(/^WARNING:/) &&
                !trimmed.match(/^ERROR:/);
        });

        // Join and clean up
        cleaned = lines.join('\n').trim();

        // If we have meaningful content, format it nicely
        if (cleaned.length > 0) {
            // Extract the most meaningful parts
            const meaningfulParts = [];

            // Look for application usage
            const appMatch = content.match(/Application:\s*([^\n]+)/);
            if (appMatch) {
                meaningfulParts.push(`Using ${appMatch[1].trim()}`);
            }

            // Look for window titles
            const titleMatch = content.match(/Window Title:\s*([^\n]+)/);
            if (titleMatch) {
                meaningfulParts.push(`Viewing: ${titleMatch[1].trim()}`);
            }

            // Look for URLs
            const urlMatch = content.match(/URL:\s*([^\n]+)/);
            if (urlMatch) {
                meaningfulParts.push(`Browsing: ${urlMatch[1].trim()}`);
            }

            // Look for visible text content
            const textMatch = content.match(/Visible Text Content and UI Elements:\s*([^]*?)(?=\n[A-Z]|$)/);
            if (textMatch) {
                const textContent = textMatch[1].trim();
                if (textContent.length > 0) {
                    meaningfulParts.push(`Content: ${textContent.substring(0, 100)}${textContent.length > 100 ? '...' : ''}`);
                }
            }

            // If we found meaningful parts, use them
            if (meaningfulParts.length > 0) {
                return meaningfulParts.join(' • ');
            }

            // Otherwise, return cleaned content (truncated if too long)
            return cleaned.length > 200 ? cleaned.substring(0, 200) + '...' : cleaned;
        }

        // Fallback: return a generic description
        return 'Screen activity recorded';
    }

    /**
     * Create HTML for a narrative timeline hour item
     */
    createNarrativeTimelineHourItem(hourGroup, index) {
        const hour = hourGroup.hour_display;
        const observationCount = hourGroup.observation_count;
        const observations = hourGroup.observations;

        return `
            <div class="narrative-timeline-hour-item" data-hour="${hourGroup.hour}">
                <div class="narrative-timeline-hour-header" onclick="window.gumboApp?.toggleNarrativeTimelineHourDetails(${hourGroup.hour})">
                    <div class="narrative-timeline-hour-info">
                        <h4 class="narrative-timeline-hour-title">
                            <i class="fas fa-clock"></i>
                            ${hour}
                        </h4>
                        <span class="narrative-timeline-hour-count">${observationCount} activities</span>
                    </div>
                    <div class="narrative-timeline-hour-toggle">
                        <i class="fas fa-chevron-down"></i>
                    </div>
                </div>
                <div class="narrative-timeline-hour-details" id="narrative-timeline-hour-${hourGroup.hour}">
                    <div class="narrative-timeline-observations">
                        ${observations.map((obs, obsIndex) => `
                            <div class="narrative-timeline-observation">
                                <div class="narrative-timeline-observation-content">
                                    <p>${this.escapeHtml(this.cleanTranscriptionData(obs.content))}</p>
                                </div>
                                <div class="narrative-timeline-observation-meta">
                                    <span class="narrative-timeline-observation-time">
                                        ${this.formatLocalTime(obs.created_at)}
                                    </span>
                                    <span class="narrative-timeline-observation-type">
                                        ${obs.content_type}
                                    </span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Setup click handlers for narrative timeline hour items
     */
    setupNarrativeTimelineHourHandlers() {
        const hourItems = document.querySelectorAll('.narrative-timeline-hour-item');

        hourItems.forEach(item => {
            const hour = item.dataset.hour;
            const details = document.getElementById(`narrative-timeline-hour-${hour}`);
            const toggle = item.querySelector('.narrative-timeline-hour-toggle i');

            if (details && toggle) {
                // Initially hide details
                details.style.display = 'none';
                toggle.classList.remove('fa-chevron-up');
                toggle.classList.add('fa-chevron-down');
            }
        });
    }

    /**
     * Toggle narrative timeline hour details visibility
     */
    toggleNarrativeTimelineHourDetails(hour) {
        const details = document.getElementById(`narrative-timeline-hour-${hour}`);
        const toggle = document.querySelector(`[data-hour="${hour}"] .narrative-timeline-hour-toggle i`);

        if (details && toggle) {
            const isVisible = details.style.display !== 'none';

            if (isVisible) {
                details.style.display = 'none';
                toggle.classList.remove('fa-chevron-up');
                toggle.classList.add('fa-chevron-down');
            } else {
                details.style.display = 'block';
                toggle.classList.remove('fa-chevron-down');
                toggle.classList.add('fa-chevron-up');
            }
        }
    }

    /**
     * Format datetime to local timezone
     */
    formatLocalTime(dateString) {
        try {
            console.log('🔥🔥🔥 formatLocalTime CALLED with input:', dateString);

            // Parse the UTC date string and convert to local time
            const date = new Date(dateString);

            console.log('Parsed date object:', date);
            console.log('Date.getTime():', date.getTime());
            console.log('Is valid:', !isNaN(date.getTime()));

            // Check if the date is valid
            if (isNaN(date.getTime())) {
                console.log('Invalid date, returning error');
                return 'Invalid time';
            }

            // If the dateString doesn't have timezone info, assume it's UTC
            // and create a proper UTC date object
            if (!dateString.includes('Z') && !dateString.includes('+')) {
                console.log('No timezone info, treating as UTC');
                // Treat as UTC and convert to local
                const utcDate = new Date(dateString + 'Z');
                if (!isNaN(utcDate.getTime())) {
                    const result = utcDate.toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                        hour12: true,
                        timeZoneName: 'short'
                    });
                    console.log('UTC conversion result:', result);
                    return result;
                }
            }

            // Format in local timezone
            const result = date.toLocaleTimeString('en-US', {
                hour: 'numeric',
                minute: '2-digit',
                hour12: true,
                timeZoneName: 'short' // This will show the timezone
            });
            console.log('Direct conversion result:', result);
            return result;
        } catch (error) {
            console.error('Error formatting time:', error);
            return 'Time error';
        }
    }

    /**
     * Get current timezone name
     */
    getCurrentTimezone() {
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone;
        } catch (error) {
            return 'Local Time';
        }
    }

    /**
     * Display empty narrative timeline state
     */
    displayEmptyNarrativeTimeline() {
        const contentContainer = document.getElementById('narrativeTimelineContent');

        if (!contentContainer) return;

        contentContainer.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-list-alt" aria-hidden="true"></i>
                <h3>No narrative timeline data</h3>
                <p>No raw observations found for the selected date. Try a different date or check if you have any observations recorded.</p>
            </div>
        `;
    }

    // =============================================================================
    // GUMBO RELIABLE SUGGESTION SYSTEM (HTTP POLLING)
    // =============================================================================

    initializeSuggestionStream() {
        const content = document.getElementById('suggestionsContent');
        if (!content) return;

        this.updateSuggestionUI('connecting');
        // Replace SSE with HTTP polling
        this.startSuggestionPolling();
    }

    startSuggestionPolling() {
        console.log('🔄 Starting suggestion HTTP polling');
        this.updateSuggestionUI('monitoring');

        // Poll for new suggestions every 5 seconds
        this.suggestionPollingInterval = setInterval(() => {
            if (this.activeTab === 'suggestions') {
                this.checkForNewSuggestions();
            }
        }, 5000);

        // Check immediately
        this.checkForNewSuggestions();
    }

    async checkForNewSuggestions() {
        try {
            // Get undelivered suggestions (like how propositions work)
            const response = await fetch(`${this.apiBaseUrl}/suggestions?delivered=false&limit=10`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();

            if (data.suggestions && data.suggestions.length > 0) {
                console.log(`🎯 Received ${data.suggestions.length} new suggestions via HTTP polling`);

                // Convert to the format expected by displaySuggestionBatch
                const batch = {
                    suggestions: data.suggestions,
                    generated_at: new Date().toISOString(),
                    batch_id: data.suggestions[0]?.batch_id || 'polling'
                };

                this.displaySuggestionBatch(batch);
            }

        } catch (error) {
            console.error('Error checking for new suggestions:', error);
            // Don't show error UI for polling failures - just log them
        }
    }

    stopSuggestionPolling() {
        if (this.suggestionPollingInterval) {
            clearInterval(this.suggestionPollingInterval);
            this.suggestionPollingInterval = null;
            console.log('⏹️ Stopped suggestion polling');
        }
    }

    connectSuggestionStream() {
        const content = document.getElementById('suggestionsContent');
        if (!content) return;

        try {
            // Close existing connection if any
            if (this.suggestionEventSource) {
                this.suggestionEventSource.close();
            }

            // Create new SSE connection
            this.suggestionEventSource = new EventSource(`${this.apiBaseUrl}/suggestions/stream`);

            // Connection opened
            this.suggestionEventSource.onopen = () => {
                console.log('✅ Suggestion stream connected');
                this.updateSuggestionUI('monitoring');
                this.suggestionReconnectAttempts = 0;
            };

            // Handle suggestion batch events
            this.suggestionEventSource.addEventListener('suggestion_batch', (event) => {
                try {
                    const batch = JSON.parse(event.data);
                    console.log('🎯 Received suggestion batch:', batch);
                    this.displaySuggestionBatch(batch);
                } catch (error) {
                    console.error('Error parsing suggestion batch:', error);
                }
            });

            // Handle heartbeat events
            this.suggestionEventSource.addEventListener('heartbeat', (event) => {
                try {
                    const heartbeat = JSON.parse(event.data);
                    console.log('💓 Suggestion stream heartbeat:', heartbeat);
                    // Update connection status if needed
                } catch (error) {
                    console.error('Error parsing heartbeat:', error);
                }
            });

            // Handle rate limit events
            this.suggestionEventSource.addEventListener('rate_limited', (event) => {
                try {
                    const rateLimitData = JSON.parse(event.data);
                    console.log('⏰ Suggestion generation rate limited:', rateLimitData);
                    this.updateSuggestionUI('rate_limited', rateLimitData);
                } catch (error) {
                    console.error('Error parsing rate limit event:', error);
                }
            });

            // Handle error events
            this.suggestionEventSource.addEventListener('error', (event) => {
                try {
                    const errorData = JSON.parse(event.data);
                    console.error('❌ Suggestion stream error:', errorData);
                    this.updateSuggestionUI('error', errorData);
                } catch (error) {
                    console.error('Error parsing error event:', error);
                }
            });

            // Connection error
            this.suggestionEventSource.onerror = (event) => {
                console.error('❌ Suggestion stream connection error:', event);

                if (this.suggestionEventSource.readyState === EventSource.CLOSED) {
                    this.handleSuggestionStreamReconnect();
                }
            };

        } catch (error) {
            console.error('Failed to create suggestion stream:', error);
            this.updateSuggestionUI('error', { message: error.message });
        }
    }

    handleSuggestionStreamReconnect() {
        const maxAttempts = 5;
        const baseDelay = 1000; // 1 second

        if (!this.suggestionReconnectAttempts) {
            this.suggestionReconnectAttempts = 0;
        }

        if (this.suggestionReconnectAttempts >= maxAttempts) {
            console.error('Max reconnection attempts reached for suggestion stream');
            this.updateSuggestionUI('disconnected');
            return;
        }

        this.suggestionReconnectAttempts++;
        const delay = baseDelay * Math.pow(2, this.suggestionReconnectAttempts - 1); // Exponential backoff

        console.log(`🔄 Reconnecting suggestion stream in ${delay}ms (attempt ${this.suggestionReconnectAttempts}/${maxAttempts})`);

        this.updateSuggestionUI('reconnecting', {
            attempt: this.suggestionReconnectAttempts,
            maxAttempts: maxAttempts
        });

        setTimeout(() => {
            this.connectSuggestionStream();
        }, delay);
    }

    updateSuggestionUI(status, data = null) {
        const content = document.getElementById('suggestionsContent');
        if (!content) return;

        switch (status) {
            case 'connecting':
                content.innerHTML = `
                    <div class="stream-status connecting">
                        <div class="status-icon">🔄</div>
                        <div class="status-text">
                            <div class="main-text">Connecting to suggestion stream...</div>
                            <div class="sub-text">Establishing real-time connection</div>
                        </div>
                </div>
            `;
                break;

            case 'monitoring':
                content.innerHTML = `
                    <div class="stream-status monitoring">
                        <div class="status-icon">👁️</div>
                        <div class="status-text">
                            <div class="main-text">Monitoring for intelligent suggestions</div>
                            <div class="sub-text">Real-time intelligent suggestions powered by behavioral insights</div>
                        </div>
                        <div class="monitoring-details">
                            <div class="detail-item">
                                <span class="detail-label">Trigger:</span>
                                <span class="detail-value">High-confidence insights (≥8)</span>
                            </div>
                            <div class="detail-item">
                                <span class="detail-label">Rate Limit:</span>
                                <span class="detail-value">Max 1 batch per minute</span>
                            </div>
                        </div>
                    </div>
                `;
                break;

            case 'rate_limited':
                const waitTime = Math.ceil(data?.wait_time_seconds || 60);
                content.innerHTML = `
                    <div class="stream-status rate-limited">
                        <div class="status-icon">⏰</div>
                        <div class="status-text">
                            <div class="main-text">Rate limited</div>
                            <div class="sub-text">Next suggestion batch available in ${waitTime} seconds</div>
                        </div>
                    </div>
                `;
                break;

            case 'reconnecting':
                content.innerHTML = `
                    <div class="stream-status reconnecting">
                        <div class="status-icon">🔄</div>
                        <div class="status-text">
                            <div class="main-text">Reconnecting...</div>
                            <div class="sub-text">Attempt ${data.attempt}/${data.maxAttempts}</div>
                        </div>
                    </div>
                `;
                break;

            case 'error':
            case 'disconnected':
                content.innerHTML = `
                    <div class="error-state">
                        <div class="error-icon">⚠️</div>
                        <h3>Stream ${status === 'error' ? 'Error' : 'Disconnected'}</h3>
                        <p>${data?.message || 'Unable to connect to suggestion stream'}</p>
                        <button class="retry-btn" onclick="window.gumboApp.initializeSuggestionStream()">🔄 Reconnect</button>
                    </div>
                `;
                break;
        }
    }

    displaySuggestionBatch(batch) {
        const content = document.getElementById('suggestionsContent');
        if (!content || !batch.suggestions || batch.suggestions.length === 0) return;

        // Store current batch for chat functionality
        this.currentSuggestionBatch = batch;

        content.innerHTML = `
            <div class="suggestions-header">
                <div class="suggestions-summary">
                    <h3>🎯 New Intelligent Suggestions</h3>
                    <div class="meta-info">
                        Triggered by proposition ${batch.trigger_proposition_id} • Generated ${this.formatTimestamp(batch.generated_at)}
                        <div class="processing-time">⚡ ${batch.processing_time_seconds.toFixed(2)}s processing time</div>
                    </div>
                </div>
            </div>
            <div class="suggestions-list">
                ${batch.suggestions.map((suggestion, index) => `
                    <div class="suggestion-card gumbo-suggestion" data-suggestion-index="${index}">
                        <div class="suggestion-header">
                            <h4 class="suggestion-title">${this.escapeHtml(suggestion.title)}</h4>
                            <div class="suggestion-meta">
                                <span class="utility-badge" data-utility="${suggestion.expected_utility}">
                                    ${suggestion.expected_utility ? suggestion.expected_utility.toFixed(2) : 'N/A'} utility
                                </span>
                                <span class="category-badge" data-category="${suggestion.category}">
                                    ${this.escapeHtml(suggestion.category)}
                                </span>
                                <span class="probability-badge">
                                    ${(suggestion.probability_useful * 100).toFixed(0)}% useful
                                </span>
                            </div>
                        </div>
                        <div class="suggestion-description">
                            ${this.escapeHtml(suggestion.description)}
                        </div>
                        <div class="suggestion-reasoning">
                            <details>
                                <summary>🧠 AI Reasoning</summary>
                                <div class="reasoning-content">
                                    ${this.escapeHtml(suggestion.rationale)}
                                </div>
                            </details>
                        </div>
                        ${suggestion.utility_scores ? `
                            <div class="utility-scores">
                                <details>
                                    <summary>📊 Utility Analysis</summary>
                                    <div class="scores-grid">
                                        <div class="score-item">
                                            <span class="score-label">Benefit:</span>
                                            <span class="score-value">${suggestion.utility_scores.benefit}/10</span>
                                        </div>
                                        <div class="score-item">
                                            <span class="score-label">False Positive Cost:</span>
                                            <span class="score-value">${suggestion.utility_scores.false_positive_cost}/10</span>
                                        </div>
                                        <div class="score-item">
                                            <span class="score-label">False Negative Cost:</span>
                                            <span class="score-value">${suggestion.utility_scores.false_negative_cost}/10</span>
                                        </div>
                                        <div class="score-item">
                                            <span class="score-label">Decay:</span>
                                            <span class="score-value">${suggestion.utility_scores.decay}/10</span>
                                        </div>
                                    </div>
                                </div>
                            </details>
                        </div>
                        ` : ''}
                        <div class="suggestion-actions">
                            <button class="action-btn" onclick="window.gumboApp.copySuggestion(${index})">
                                📋 Copy
                            </button>
                            <button class="action-btn" onclick="window.gumboApp.chatAboutSuggestion(${index})">
                                💬 Discuss
                            </button>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        this.currentSuggestions = batch.suggestions;
        this.showToast('New suggestions received!', 'success');
    }

    // Helper methods for suggestion actions
    copySuggestion(index) {
        if (!this.currentSuggestions || !this.currentSuggestions[index]) return;

        const suggestion = this.currentSuggestions[index];
        const text = `${suggestion.title}\n\n${suggestion.description}\n\nRationale: ${suggestion.rationale}`;

        navigator.clipboard.writeText(text).then(() => {
            this.showToast('Suggestion copied to clipboard!', 'success');
        }).catch(err => {
            console.error('Failed to copy suggestion:', err);
            this.showToast('Failed to copy suggestion', 'error');
        });
    }

    chatAboutSuggestion(index) {
        if (!this.currentSuggestionBatch || !this.currentSuggestionBatch.suggestions || !this.currentSuggestionBatch.suggestions[index]) return;

        const suggestion = this.currentSuggestionBatch.suggestions[index];

        // Create unique chat ID for this suggestion
        const chatId = `suggestion_${this.currentSuggestionBatch.batch_id}_${index}`;

        // Create or get existing chat thread
        this.createSuggestionChat(chatId, suggestion, this.currentSuggestionBatch);

        // Switch to chat interface
        this.switchTab('chat');
        this.showToast(`Starting discussion about: ${suggestion.title}`, 'info');
    }

    createSuggestionChat(chatId, suggestion, batch) {
        // Check if chat already exists
        if (this.activeSuggestionChats[chatId]) {
            this.switchToChat(chatId);
            return;
        }

        // Create new chat thread
        const chatThread = {
            id: chatId,
            suggestion: suggestion,
            batch: batch,
            messages: [
                {
                    role: 'assistant',
                    content: `I'd be happy to discuss this suggestion with you:\n\n**${suggestion.title}**\n\n${suggestion.description}\n\nWhat would you like to know more about?`,
                    timestamp: new Date().toISOString()
                }
            ],
            created_at: new Date().toISOString(),
            last_activity: new Date().toISOString()
        };

        // Store chat thread
        this.activeSuggestionChats[chatId] = chatThread;

        // Update chat sidebar
        this.updateChatSidebar();

        // Switch to this chat
        this.switchToChat(chatId);
    }

    switchToChat(chatId) {
        this.currentChatId = chatId;
        this.loadChatMessages(chatId);
        this.updateChatUI();
    }

    displaySuggestions(suggestionsData) {
        const content = document.getElementById('suggestionsContent');

        if (!suggestionsData.suggestions || suggestionsData.suggestions.length === 0) {
            content.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-lightbulb"></i>
                    <h3>No suggestions available</h3>
                    <p>No actionable suggestions found based on your recent activity. Try increasing the time range or continue using the system to generate more data.</p>
                </div>
            `;
            return;
        }

        // Group suggestions by urgency/time
        const suggestionsByTime = {
            'now': [],
            'today': [],
            'this_week': []
        };

        suggestionsData.suggestions.forEach(suggestion => {
            const urgency = suggestion.urgency || 'today';
            if (suggestionsByTime[urgency]) {
                suggestionsByTime[urgency].push(suggestion);
            } else {
                suggestionsByTime['today'].push(suggestion);
            }
        });

        let suggestionsHtml = '';

        // Create sections for each time group
        if (suggestionsByTime.now.length > 0) {
            suggestionsHtml += this.createSuggestionsTimeSection('Now', suggestionsByTime.now);
        }

        if (suggestionsByTime.today.length > 0) {
            suggestionsHtml += this.createSuggestionsTimeSection('Today', suggestionsByTime.today);
        }

        if (suggestionsByTime.this_week.length > 0) {
            suggestionsHtml += this.createSuggestionsTimeSection('This Week', suggestionsByTime.this_week);
        }

        content.innerHTML = suggestionsHtml;

        // Add event listeners to Open Chat buttons
        this.setupSuggestionChatButtons();

        this.showToast('Suggestions generated successfully!', 'success');
    }

    createSuggestionsTimeSection(timeLabel, suggestions) {
        let sectionHtml = `
            <div class="suggestions-time-section">
                <h3 class="suggestions-time-header">${timeLabel}</h3>
                <div class="suggestions-grid">
        `;

        suggestions.forEach((suggestion, index) => {
            // Clean the description for safe HTML insertion
            const cleanDescription = suggestion.description.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
            const suggestionJson = JSON.stringify(suggestion).replace(/"/g, '&quot;');

            sectionHtml += `
                <div class="suggestion-card" data-suggestion-id="${index}">
                    <h4 class="suggestion-title">${suggestion.title}</h4>
                    
                    <div class="suggestion-description">
                        ${suggestion.description}
                </div>
                    
                    <button class="suggestion-open-chat" data-suggestion="${suggestionJson}">
                        <i class="fas fa-comments"></i>
                        Open Chat
                    </button>
            </div>
        `;
        });

        sectionHtml += `
                </div>
            </div>
        `;

        return sectionHtml;
    }

    setupSuggestionChatButtons() {
        const chatButtons = document.querySelectorAll('.suggestion-open-chat');
        chatButtons.forEach(button => {
            button.addEventListener('click', (e) => {
                try {
                    const suggestionData = JSON.parse(e.target.closest('.suggestion-open-chat').dataset.suggestion.replace(/&quot;/g, '"'));
                    this.openSuggestionChat(suggestionData);
                } catch (error) {
                    console.error('Error parsing suggestion data:', error);
                    this.showToast('Error opening chat', 'error');
                }
            });
        });
    }

    openSuggestionChat(suggestion) {
        console.log('Opening chat for suggestion:', suggestion);

        // Open the chat modal
        this.openChatModal();

        // Initialize or switch to this chat
        this.initializeSuggestionChat(suggestion);
    }

    // ================================
    // Chat System Implementation
    // ================================

    openChatModal() {
        const chatModal = document.getElementById('chatModal');
        if (chatModal) {
            chatModal.style.display = 'flex';
            chatModal.setAttribute('aria-hidden', 'false');

            // Setup modal event listeners if not already done
            if (!this.chatModalInitialized) {
                this.setupChatModalListeners();
                this.chatModalInitialized = true;
            }
        }
    }

    closeChatModal() {
        const chatModal = document.getElementById('chatModal');
        if (chatModal) {
            chatModal.style.display = 'none';
            chatModal.setAttribute('aria-hidden', 'true');
        }
    }

    setupChatModalListeners() {
        // Close button
        const closeBtn = document.getElementById('closeChatModal');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.closeChatModal());
        }

        // Close on backdrop click
        const chatModal = document.getElementById('chatModal');
        if (chatModal) {
            chatModal.addEventListener('click', (e) => {
                if (e.target === chatModal) {
                    this.closeChatModal();
                }
            });
        }

        // Escape key to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && chatModal && chatModal.style.display === 'flex') {
                this.closeChatModal();
            }
        });

        // Chat input handling
        const chatInput = document.getElementById('chatInput');
        const chatSendBtn = document.getElementById('chatSendBtn');

        if (chatInput) {
            // Auto-resize textarea
            chatInput.addEventListener('input', () => {
                this.updateCharCount();
                this.autoResizeTextarea(chatInput);
                this.toggleSendButton();
            });

            // Send on Enter (but not Shift+Enter)
            chatInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendChatMessage();
                }
            });
        }

        if (chatSendBtn) {
            chatSendBtn.addEventListener('click', () => this.sendChatMessage());
        }
    }

    updateCharCount() {
        const chatInput = document.getElementById('chatInput');
        const charCount = document.getElementById('charCount');

        if (chatInput && charCount) {
            const length = chatInput.value.length;
            charCount.textContent = `${length}/2000`;

            // Update styling based on character count
            charCount.classList.remove('warning', 'error');
            if (length > 1800) {
                charCount.classList.add('error');
            } else if (length > 1500) {
                charCount.classList.add('warning');
            }
        }
    }

    autoResizeTextarea(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    }

    toggleSendButton() {
        const chatInput = document.getElementById('chatInput');
        const chatSendBtn = document.getElementById('chatSendBtn');

        if (chatInput && chatSendBtn) {
            const hasText = chatInput.value.trim().length > 0;
            const withinLimit = chatInput.value.length <= 2000;
            chatSendBtn.disabled = !hasText || !withinLimit;
        }
    }

    initializeSuggestionChat(suggestion) {
        // Store current chat context
        this.currentChatContext = {
            suggestion: suggestion,
            messages: [],
            conversationId: null
        };

        // Update chat header
        const chatTitle = document.getElementById('chatTitle');
        if (chatTitle) {
            chatTitle.textContent = suggestion.title;
        }

        // Show input area
        const chatInputArea = document.getElementById('chatInputArea');
        if (chatInputArea) {
            chatInputArea.style.display = 'block';
        }

        // Clear and setup messages area
        this.displayChatWelcome(suggestion);

        // Add to chat list sidebar
        this.addToActiveChatsList(suggestion);

        // Focus on input
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.focus();
        }
    }

    displayChatWelcome(suggestion) {
        const chatMessages = document.getElementById('chatMessages');
        if (!chatMessages) return;

        const welcomeHtml = `
            <div class="chat-message assistant">
                <div class="message-content">
                    <p><strong>${suggestion.title}</strong></p>
                    <p>${suggestion.description}</p>
                    
                    ${suggestion.action_items && suggestion.action_items.length > 0 ? `
                        <div style="margin-top: 1rem;">
                            <strong>Suggested Actions:</strong>
                            <ul style="margin: 0.5rem 0; padding-left: 1.5rem;">
                                ${suggestion.action_items.map(item => `<li>${item}</li>`).join('')}
                            </ul>
                        </div>
                    ` : ''}
                    
                    <p style="margin-top: 1rem; font-style: italic; color: var(--text-secondary);">
                        Hi! I'm here to help you with this suggestion. Feel free to ask questions or let me know how you'd like to proceed.
                    </p>
                </div>
                <div class="message-meta">
                    <span class="message-time">${this.getTimeAgo(suggestion.created_at)}</span>
                        </div>
                    </div>
                `;

        chatMessages.innerHTML = welcomeHtml;
        this.scrollToBottom(chatMessages);
    }

    addToActiveChatsList(suggestion) {
        const chatList = document.getElementById('chatList');
        if (!chatList) return;

        // Check if this chat already exists
        const existingChat = chatList.querySelector(`[data-chat-id="${suggestion.title}"]`);
        if (existingChat) {
            // Mark as active
            chatList.querySelectorAll('.chat-list-item').forEach(item => item.classList.remove('active'));
            existingChat.classList.add('active');
            return;
        }

        // Create new chat list item
        const chatItem = document.createElement('div');
        chatItem.className = 'chat-list-item active';
        chatItem.dataset.chatId = suggestion.title;

        const preview = suggestion.description.length > 60
            ? suggestion.description.substring(0, 60) + '...'
            : suggestion.description;

        chatItem.innerHTML = `
            <div class="chat-item-title">${suggestion.title}</div>
            <div class="chat-item-preview">${preview}</div>
            <div class="chat-item-time">${this.getTimeAgo(suggestion.created_at)}</div>
        `;

        // Add click handler
        chatItem.addEventListener('click', () => {
            this.switchToChat(suggestion);
        });

        // Mark other chats as inactive
        chatList.querySelectorAll('.chat-list-item').forEach(item => item.classList.remove('active'));

        // Add to top of list
        chatList.insertBefore(chatItem, chatList.firstChild);

        // Remove empty state if present
        const emptyState = chatList.querySelector('.chat-list-empty');
        if (emptyState) {
            emptyState.remove();
        }
    }

    switchToChat(suggestion) {
        // Update active chat in sidebar
        const chatList = document.getElementById('chatList');
        if (chatList) {
            chatList.querySelectorAll('.chat-list-item').forEach(item => {
                item.classList.remove('active');
                if (item.dataset.chatId === suggestion.title) {
                    item.classList.add('active');
                }
            });
        }

        // Load chat context
        this.initializeSuggestionChat(suggestion);
    }

    async sendChatMessage() {
        const chatInput = document.getElementById('chatInput');
        if (!chatInput || !this.currentChatContext) return;

        const message = chatInput.value.trim();
        if (!message) return;

        // Disable input while processing
        chatInput.disabled = true;
        const chatSendBtn = document.getElementById('chatSendBtn');
        if (chatSendBtn) {
            chatSendBtn.disabled = true;
        }

        try {
            // Add user message to UI
            this.addMessageToChat('user', message);

            // Clear input
            chatInput.value = '';
            this.updateCharCount();
            this.autoResizeTextarea(chatInput);

            // Show typing indicator
            this.showTypingIndicator();

            // Prepare chat request
            const chatRequest = {
                message: message,
                suggestion_context: this.currentChatContext.suggestion,
                chat_history: this.currentChatContext.messages.slice(-10) // Last 10 messages
            };

            // Send to backend
            const response = await fetch(`${this.apiBaseUrl}/chat/suggestion?user_name=Arnav Sharma`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(chatRequest)
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const chatResponse = await response.json();

            // Hide typing indicator
            this.hideTypingIndicator();

            // Add assistant response to UI
            this.addMessageToChat('assistant', chatResponse.message);

            // Store conversation ID
            if (chatResponse.conversation_id) {
                this.currentChatContext.conversationId = chatResponse.conversation_id;
            }

        } catch (error) {
            console.error('Error sending chat message:', error);
            this.hideTypingIndicator();
            this.addMessageToChat('assistant', 'Sorry, I encountered an error processing your message. Please try again.');
            this.showToast('Failed to send message', 'error');
        } finally {
            // Re-enable input
            chatInput.disabled = false;
            chatInput.focus();
            this.toggleSendButton();
        }
    }

    addMessageToChat(role, content) {
        const chatMessages = document.getElementById('chatMessages');
        if (!chatMessages) return;

        const timestamp = new Date().toISOString();
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${role}`;

        messageDiv.innerHTML = `
            <div class="message-content">${this.formatMessageContent(content)}</div>
            <div class="message-meta">
                <span class="message-time">Just now</span>
            </div>
        `;

        chatMessages.appendChild(messageDiv);
        this.scrollToBottom(chatMessages);

        // Store in chat context
        if (this.currentChatContext) {
            this.currentChatContext.messages.push({
                role: role,
                content: content,
                timestamp: timestamp
            });
        }
    }

    formatMessageContent(content) {
        // Basic markdown-style formatting
        return content
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`(.*?)`/g, '<code>$1</code>');
    }

    showTypingIndicator() {
        const typingIndicator = document.getElementById('typingIndicator');
        const statusIndicator = document.querySelector('.status-indicator');
        const chatStatus = document.getElementById('chatStatus');

        if (typingIndicator) {
            typingIndicator.style.display = 'flex';
        }

        if (statusIndicator) {
            statusIndicator.classList.add('typing');
        }

        if (chatStatus) {
            chatStatus.textContent = 'Thinking...';
        }
    }

    hideTypingIndicator() {
        const typingIndicator = document.getElementById('typingIndicator');
        const statusIndicator = document.querySelector('.status-indicator');
        const chatStatus = document.getElementById('chatStatus');

        if (typingIndicator) {
            typingIndicator.style.display = 'none';
        }

        if (statusIndicator) {
            statusIndicator.classList.remove('typing');
        }

        if (chatStatus) {
            chatStatus.textContent = 'Ready';
        }
    }

    scrollToBottom(element) {
        if (element) {
            element.scrollTop = element.scrollHeight;
        }
    }

    getTimeAgo(timestamp) {
        const now = new Date();
        const time = new Date(timestamp);
        const diffInSeconds = Math.floor((now - time) / 1000);

        if (diffInSeconds < 60) return 'Just now';
        if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)} min ago`;
        if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)} hr ago`;
        return `${Math.floor(diffInSeconds / 86400)} days ago`;
    }

    // Dashboard functionality
    startTracking() {
        // This will start the CLI tracking via Electron
        if (window.electronAPI && window.electronAPI.startCliTracking) {
            window.electronAPI.startCliTracking();
            this.updateTrackingStatus('Starting...');
        } else {
            console.log('Electron API not available');
        }
    }

    updateTrackingStatus(status) {
        const statusElement = document.getElementById('tracking-status');
        if (statusElement) {
            statusElement.textContent = status;
        }
    }

    updateDataStatus(status) {
        const dataElement = document.getElementById('data-status');
        if (dataElement) {
            dataElement.textContent = status;
        }
    }

    async loadDashboardData() {
        try {
            // Check tracking status
            if (window.electronAPI && window.electronAPI.getCliStatus) {
                const status = await window.electronAPI.getCliStatus();
                this.updateTrackingStatus(status.isRunning ? 'Active' : 'Stopped');
            }

            // Check data status
            const response = await fetch(`${this.apiBaseUrl}/propositions/count`);
            if (response.ok) {
                const data = await response.json();
                this.updateDataStatus(`${data.count} insights generated`);
            } else {
                this.updateDataStatus('No data yet');
            }

            // Load recent activity
            this.loadRecentActivity();
        } catch (error) {
            console.error('Error loading dashboard data:', error);
            this.updateTrackingStatus('Error');
            this.updateDataStatus('Error loading data');
        }
    }

    async loadRecentActivity() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/propositions?limit=3&sort_by=created_at`);
            if (response.ok) {
                const data = await response.json();
                this.displayRecentActivity(data.propositions || []);
            } else {
                this.displayRecentActivity([]);
            }
        } catch (error) {
            console.error('Error loading recent activity:', error);
            this.displayRecentActivity([]);
        }
    }

    displayRecentActivity(propositions) {
        const activityPreview = document.getElementById('activity-preview');
        if (!activityPreview) return;

        if (propositions.length === 0) {
            activityPreview.innerHTML = '<p class="loading-text">No insights generated yet. Start tracking to see your first insights!</p>';
            return;
        }

        const activityHTML = propositions.map(prop => `
            <div class="activity-item">
                <div class="activity-icon">
                    <i class="fas fa-lightbulb"></i>
                </div>
                <div class="activity-content">
                    <p class="activity-text">${prop.text.substring(0, 100)}${prop.text.length > 100 ? '...' : ''}</p>
                    <span class="activity-time">${new Date(prop.created_at).toLocaleDateString()}</span>
                </div>
            </div>
        `).join('');

        activityPreview.innerHTML = activityHTML;
    }

}



// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.gumboApp = new GumboApp();
});

// Add CSS for results display dynamically
const additionalCSS = `
.results-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
    gap: var(--spacing-lg);
}

.result-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-lg);
    overflow: hidden;
    box-shadow: var(--shadow-sm);
}

.result-card.full-width {
    grid-column: 1 / -1;
}

.result-header {
    background: linear-gradient(135deg, var(--primary-color), var(--primary-custom-tooltip-color));
    color: var(--text-white);
    padding: var(--spacing-lg);
}

.result-header h3 {
    margin: 0;
    font-size: var(--font-size-lg);
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
}

.result-content {
    padding: var(--spacing-lg);
}

.summary-stats {
    display: grid;
    gap: var(--spacing-md);
}

.stat {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--spacing-sm) 0;
    border-bottom: 1px solid var(--border-light);
}

.stat:last-child {
    border-bottom: none;
}

.stat-label {
    color: var(--text-secondary);
    font-weight: 500;
}

.stat-value {
    font-weight: 600;
    color: var(--text-primary);
}

.stat-value.success {
    color: var(--success-color);
}

.insights-list, .patterns-list {
    display: flex;
    flex-direction: column;
    gap: var(--spacing-md);
}

.insight-item, .pattern-item {
    display: flex;
    align-items: flex-start;
    gap: var(--spacing-sm);
    padding: var(--spacing-sm);
    background: var(--bg-secondary);
    border-radius: var(--border-radius);
}

.insight-icon {
    color: var(--primary-color);
    font-size: var(--font-size-lg);
    flex-shrink: 0;
}

.insight-text {
    flex: 1;
    color: var(--text-primary);
}

.pattern-name {
    font-weight: 600;
    color: var(--text-primary);
}

.pattern-confidence {
    font-size: var(--font-size-sm);
    color: var(--text-secondary);
}

.analysis-details {
    background: var(--bg-secondary);
    border: 1px solid var(--border-light);
    border-radius: var(--border-radius);
    padding: var(--spacing-lg);
    font-family: var(--font-family-mono);
    font-size: var(--font-size-sm);
    color: var(--text-primary);
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow-x: auto;
    max-height: 400px;
    overflow-y: auto;
}

.history-item {
    background: var(--bg-secondary);
    border: 1px solid var(--border-light);
    border-radius: var(--border-radius);
    padding: var(--spacing-lg);
    margin-bottom: var(--spacing-md);
}

.history-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: var(--spacing-sm);
}

.history-title {
    font-weight: 600;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
}

.history-date {
    font-size: var(--font-size-sm);
    color: var(--text-secondary);
}

.history-details {
    display: flex;
    gap: var(--spacing-lg);
    font-size: var(--font-size-sm);
    color: var(--text-secondary);
    margin-bottom: var(--spacing-sm);
}

.history-content {
    font-size: var(--font-size-sm);
    color: var(--text-primary);
    line-height: 1.4;
}

.no-data {
    text-align: center;
    color: var(--text-muted);
    font-style: italic;
    padding: var(--spacing-xl);
}

@media (max-width: 768px) {
    .results-grid {
        grid-template-columns: 1fr;
    }
    
    .history-header {
        flex-direction: column;
        align-items: flex-start;
        gap: var(--spacing-sm);
    }
    
    .history-details {
        flex-direction: column;
        gap: var(--spacing-sm);
    }
}
`;

// Inject additional CSS
const style = document.createElement('style');
style.textContent = additionalCSS;
document.head.appendChild(style);
