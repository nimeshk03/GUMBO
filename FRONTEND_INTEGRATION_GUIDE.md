# Gumbo Frontend Integration Guide

This guide explains how to integrate the monitoring control JavaScript snippet seamlessly with your existing gumbo.app frontend.

## 🚀 Quick Start

### 1. Include the Files

Add these files to your `frontend/` directory:

```bash
frontend/
├── static/
│   ├── css/
│   │   └── monitoring-control.css    # New monitoring styles
│   └── js/
│       └── monitoring-control.js     # New monitoring logic
└── index.html                         # Updated to include new files
```

### 2. Update Your HTML

Add these lines to your `index.html`:

```html
<!-- In the <head> section -->
<link rel="stylesheet" href="static/css/monitoring-control.css?v=1">

<!-- Before closing </body> tag -->
<script src="static/js/monitoring-control.js?v=1"></script>
```

### 3. Deploy to gumbo.app

The monitoring control will automatically appear on your hosted site and integrate seamlessly with your existing UI.

## 🎯 What Gets Added

### Visual Components

- **Monitoring Control Panel**: Appears in the Home tab below the welcome section
- **Connection Status**: Real-time indicator showing local backend connectivity
- **Monitoring Status**: Shows if monitoring is active/inactive
- **Control Button**: Toggle to start/stop monitoring
- **Input Fields**: User name and AI model selection
- **Status Messages**: Success, error, and warning notifications

### Functionality

- **Automatic Detection**: Only loads on `gumbo.app` domain
- **Connection Monitoring**: Checks local backend every 30 seconds
- **Status Polling**: Updates monitoring status every 10 seconds
- **Error Handling**: Graceful fallbacks for connection issues
- **Responsive Design**: Works on all device sizes

## 🔧 How It Works

### 1. Domain Detection

The script automatically detects if it's running on the hosted domain:

```javascript
if (window.location.hostname === 'gumbo.app' || 
    window.location.hostname === 'www.gumbo.app') {
    // Initialize monitoring control
    window.gumboMonitoring = new GumboMonitoringControl();
}
```

### 2. UI Integration

The monitoring control is inserted into the existing Home tab:

```javascript
insertIntoHomeTab() {
    const homePanel = document.getElementById('home-panel');
    const homeContent = homePanel.querySelector('.home-content');
    const welcomeSection = homeContent.querySelector('.welcome-section');
    
    // Insert after welcome section
    welcomeSection.parentNode.insertBefore(
        this.monitoringContainer, 
        welcomeSection.nextSibling
    );
}
```

### 3. API Communication

Uses the new monitoring endpoints we added to the backend:

- `POST /monitoring/start` - Start monitoring
- `POST /monitoring/stop` - Stop monitoring  
- `GET /monitoring/status` - Get current status

## 🎨 Design Integration

### CSS Variables

The monitoring control uses your existing CSS custom properties:

```css
.monitoring-control-container {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: var(--border-radius-lg);
    box-shadow: var(--shadow-lg);
}
```

### Theme Support

Automatically supports your light/dark theme system:

```css
[data-theme="dark"] .monitoring-control-container {
    background: var(--bg-card);
    border-color: var(--border-color);
}
```

### Responsive Design

Follows your existing responsive patterns:

```css
@media (max-width: 768px) {
    .monitoring-control-container {
        padding: var(--spacing-lg);
        margin: var(--spacing-lg) 0;
    }
}
```

## 🔌 Technical Details

### Class Structure

```javascript
class GumboMonitoringControl {
    constructor() {
        this.localBackendUrl = 'http://localhost:8001';
        this.hostedDomain = 'https://gumbo.app';
        this.pollingInterval = 10000; // 10 seconds
        // ... other properties
    }
    
    async init() { /* Initialize UI and start monitoring */ }
    setupUI() { /* Create and insert UI elements */ }
    checkConnection() { /* Test local backend connectivity */ }
    startMonitoring() { /* Start monitoring process */ }
    stopMonitoring() { /* Stop monitoring process */ }
    // ... other methods
}
```

### Event Handling

Integrates with your existing event system:

```javascript
setupEventListeners() {
    if (this.monitoringToggle) {
        this.monitoringToggle.addEventListener('click', 
            () => this.handleToggleClick()
        );
    }
    
    if (this.userNameInput) {
        this.userNameInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                this.handleToggleClick();
            }
        });
    }
}
```

### Error Handling

Graceful fallbacks for various error scenarios:

```javascript
async checkConnection() {
    try {
        const response = await fetch(`${this.localBackendUrl}/health`, {
            method: 'GET',
            mode: 'cors',
            signal: AbortSignal.timeout(5000)
        });
        
        if (response.ok) {
            this.isConnected = true;
        } else {
            this.isConnected = false;
        }
    } catch (error) {
        this.isConnected = false;
        
        if (error.name === 'AbortError') {
            console.log('Connection check timed out');
        } else if (error.name === 'TypeError' && 
                   error.message.includes('Failed to fetch')) {
            console.log('CORS or connection error - local backend not reachable');
        }
    }
}
```

## 🚦 User Experience Flow

### 1. Initial Load
- User visits `https://gumbo.app`
- Monitoring control appears in Home tab
- Connection status shows "Checking..."

### 2. Connection Check
- Script attempts to connect to `http://localhost:8001`
- If successful: Connection status shows "Connected" (green)
- If failed: Connection status shows "Disconnected" (red)

### 3. Starting Monitoring
- User enters their name and selects AI model
- Clicks "Start Monitoring" button
- Button shows loading state
- On success: Button changes to "Stop Monitoring" (red)
- Input fields are hidden, details are shown

### 4. Active Monitoring
- Status shows "Active" (green)
- Details show user name, model, and uptime
- Status polls every 10 seconds for updates
- User can click "Stop Monitoring" to stop

### 5. Stopping Monitoring
- Button shows loading state
- On success: Button returns to "Start Monitoring" (blue)
- Input fields are shown again
- Details are hidden

## 🛠️ Customization Options

### Change Polling Interval

```javascript
// In monitoring-control.js
this.pollingInterval = 5000; // Change to 5 seconds
```

### Modify UI Position

```javascript
// Change where the monitoring control appears
insertIntoHomeTab() {
    // Instead of after welcome section, put it at the top
    const homeContent = homePanel.querySelector('.home-content');
    homeContent.insertBefore(this.monitoringContainer, homeContent.firstChild);
}
```

### Add Custom Styling

```css
/* In monitoring-control.css */
.monitoring-control-container {
    /* Your custom styles */
    border: 2px solid var(--brand-primary);
    background: linear-gradient(135deg, var(--bg-card) 0%, var(--bg-secondary) 100%);
}
```

## 🔍 Debugging

### Console Access

The monitoring control is exposed globally for debugging:

```javascript
// In browser console
window.gumboMonitoring // Access the monitoring instance
window.gumboMonitoringControl // Alternative access
```

### Logging

Comprehensive logging for troubleshooting:

```javascript
console.log('Gumbo Monitoring Control initialized');
console.log('Started monitoring status polling');
console.log('Connection check timed out');
console.log('CORS or connection error - local backend not reachable');
```

### Common Issues

1. **"Backend Unavailable" button**
   - Local backend not running
   - CORS not configured properly
   - Firewall blocking localhost:8001

2. **Connection status stuck on "Checking..."**
   - Network timeout
   - Backend health endpoint not responding

3. **Monitoring won't start**
   - User name not entered
   - Backend monitoring endpoints not working
   - Another monitoring process already running

## 📱 Mobile Support

The monitoring control is fully responsive:

- **Desktop**: Full layout with side-by-side elements
- **Tablet**: Stacked layout with adjusted spacing
- **Mobile**: Single-column layout with full-width buttons

## ♿ Accessibility Features

- **Keyboard Navigation**: Full keyboard support
- **Screen Readers**: Proper ARIA labels and roles
- **High Contrast**: Supports high contrast mode
- **Reduced Motion**: Respects user motion preferences
- **Focus Management**: Clear focus indicators

## 🔒 Security Considerations

- **Local Only**: Only communicates with localhost:8001
- **No Authentication**: Relies on local network security
- **CORS Required**: Backend must allow `gumbo.app` origin
- **HTTPS to HTTP**: Secure site to local backend communication

## 🚀 Deployment Checklist

- [ ] Upload `monitoring-control.css` to `frontend/static/css/`
- [ ] Upload `monitoring-control.js` to `frontend/static/js/`
- [ ] Update `index.html` to include both files
- [ ] Deploy to `gumbo.app`
- [ ] Test connection to local backend
- [ ] Verify monitoring start/stop functionality
- [ ] Check responsive design on mobile devices

## 🎉 Result

After integration, your gumbo.app users will see a professional monitoring control panel that:

- ✅ Seamlessly integrates with your existing design
- ✅ Provides real-time local monitoring control
- ✅ Handles errors gracefully with user-friendly messages
- ✅ Works perfectly on all devices
- ✅ Maintains your app's performance and reliability

The monitoring control becomes a natural part of your app's functionality, allowing users to control their local GUM monitoring agent directly from your hosted interface!
