import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div data-testid="error-boundary" className="flex h-screen items-center justify-center bg-[#f4f6f8] p-8">
          <div className="max-w-md rounded-lg border border-[#e1e5ea] bg-white p-6 text-center">
            <p className="text-sm font-semibold text-[#1f2933]">Что-то пошло не так</p>
            <p className="mt-2 break-words text-xs text-[#6b7785]">{this.state.error.message}</p>
            <button
              type="button"
              className="mt-4 rounded-md bg-[#2f80ed] px-3 py-1.5 text-xs text-white"
              onClick={() => this.setState({ error: null })}
            >
              Повторить
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
