// Integration example for using React components in the existing vanilla JS application

declare global {
  interface Window {
    gumboApp: any;
  }
}

import { mountDatetimePicker } from './utils/react-bridge';

// Example usage in the existing GumboApp class
export function integrateDatetimePicker() {
  // Example: Mount the datetime picker in a specific element
  const datetimePickerRoot = mountDatetimePicker('datetime-picker-container', {
    onDateChange: (date) => {
      console.log('Date selected:', date);
      // Handle the date change in the existing application
      if (window.gumboApp) {
        // You can call methods on the existing GumboApp instance
        // window.gumboApp.handleDateChange(date);
      }
    },
    initialValue: new Date(),
    className: 'datetime-picker-wrapper'
  });

  return datetimePickerRoot;
}

// Example: Cleanup function
export function cleanupDatetimePicker() {
  // This will be called when the component needs to be unmounted
  // import { unmountReactComponent } from './utils/react-bridge';
  // unmountReactComponent('datetime-picker-container');
}
