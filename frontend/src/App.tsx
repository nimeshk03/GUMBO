
import { DatetimePickerDemo } from './components/ui/datetime-picker-demo'

function App() {
  return (
    <div className="min-h-screen bg-background p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-8">Gumbo React Components</h1>

        <div className="space-y-8">
          <div className="card p-6 border rounded-lg">
            <h2 className="text-xl font-semibold mb-4">Datetime Picker Component</h2>
            <p className="text-muted-foreground mb-4">
              A modern datetime picker component built with React and TypeScript.
            </p>
            <DatetimePickerDemo />
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
