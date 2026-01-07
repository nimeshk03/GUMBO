# React Component Integration Setup

This document explains how to set up and use React components in the existing Gumbo frontend application.

## Prerequisites

1. **Node.js** (version 16 or higher)
2. **npm** or **yarn** package manager

## Installation Steps

### 1. Install Dependencies

Navigate to the `frontend` directory and install the required dependencies:

```bash
cd frontend
npm install
```

This will install:
- React 18.2.0
- React DOM 18.2.0
- TypeScript 5.2.2
- Vite 4.5.0
- Tailwind CSS 3.3.5
- Timescape 0.1.0 (for datetime picker)
- Framer Motion 10.16.4
- Other utility libraries

### 2. Project Structure

The React components are organized in the following structure:

```
frontend/
├── src/
│   ├── components/
│   │   └── ui/
│   │       ├── datetime-picker.tsx      # Main datetime picker component
│   │       ├── datetime-picker-demo.tsx # Demo component
│   │       └── input.tsx                # shadcn input component
│   ├── lib/
│   │   └── utils.ts                     # Utility functions
│   ├── utils/
│   │   └── react-bridge.ts              # Bridge for vanilla JS integration
│   ├── App.tsx                          # Main React app
│   ├── main.tsx                         # React entry point
│   └── index.css                        # Tailwind CSS
├── package.json                         # Dependencies and scripts
├── tsconfig.json                        # TypeScript configuration
├── vite.config.ts                       # Vite configuration
├── tailwind.config.js                   # Tailwind CSS configuration
└── postcss.config.js                    # PostCSS configuration
```

### 3. Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run preview` - Preview production build
- `npm run type-check` - Run TypeScript type checking

## Usage

### Using the DatetimePicker Component

#### Option 1: Standalone React App

To run the React components as a standalone application:

```bash
npm run dev
```

This will start a development server at `http://localhost:3000` with the datetime picker demo.

#### Option 2: Integration with Existing Vanilla JS App

To integrate the React datetime picker into the existing vanilla JavaScript application:

1. **Add a container element** in your HTML:

```html
<div id="datetime-picker-container"></div>
```

2. **Import and use the bridge** in your JavaScript:

```javascript
// In your existing app.js or similar
import { mountDatetimePicker } from './src/utils/react-bridge';

// Mount the datetime picker
const datetimePicker = mountDatetimePicker('datetime-picker-container', {
  onDateChange: (date) => {
    console.log('Date selected:', date);
    // Handle the date change in your existing application
  },
  initialValue: new Date(),
  className: 'datetime-picker-wrapper'
});
```

3. **Cleanup when needed**:

```javascript
import { unmountReactComponent } from './src/utils/react-bridge';

// Unmount the component
unmountReactComponent('datetime-picker-container');
```

### Component Props

The `DatetimePickerBridge` component accepts the following props:

- `onDateChange?: (date: Date | undefined) => void` - Callback when date changes
- `initialValue?: Date` - Initial date value
- `className?: string` - Additional CSS classes

## Development

### Adding New React Components

1. Create your component in `src/components/ui/`
2. Export it from the appropriate index file
3. Add it to the bridge utilities if needed
4. Update the documentation

### Styling

The project uses Tailwind CSS for styling. You can:

1. Add custom styles in `src/index.css`
2. Use Tailwind classes directly in components
3. Extend the Tailwind configuration in `tailwind.config.js`

### TypeScript

The project is fully typed with TypeScript. Make sure to:

1. Add proper types for all props and state
2. Use the `@/` alias for imports from the src directory
3. Run `npm run type-check` to verify types

## Troubleshooting

### Common Issues

1. **Module not found errors**: Make sure all dependencies are installed with `npm install`
2. **TypeScript errors**: Run `npm run type-check` to identify issues
3. **Styling issues**: Ensure Tailwind CSS is properly configured
4. **React component not rendering**: Check that the container element exists and has the correct ID

### Build Issues

If you encounter build issues:

1. Clear node_modules and reinstall: `rm -rf node_modules && npm install`
2. Clear build cache: `rm -rf dist && npm run build`
3. Check TypeScript configuration: `npm run type-check`

## Integration with Existing App

The React components are designed to work alongside the existing vanilla JavaScript application. The bridge utilities allow you to:

1. Mount React components into existing DOM elements
2. Communicate between React and vanilla JS
3. Clean up React components when needed

This hybrid approach allows you to gradually migrate to React while maintaining the existing functionality.
