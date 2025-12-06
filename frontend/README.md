# Kyrandia Navigator Frontend

A view-only navigator UI for exploring Kyrandia game fixtures. Built with Vite, React, and TypeScript, this frontend provides a health check interface to validate backend API connectivity.

## Purpose

The frontend serves as a read-only navigator for the Kyrandia game world, starting with a health check page that validates connectivity to the backend API endpoints. It exercises the `/world/locations` endpoint at startup to verify that the backend is reachable and returning expected data.

## Getting Started

### Prerequisites

- Node.js (v18 or later recommended)
- npm or yarn

### Installation

```bash
npm install
```

### Environment Configuration

Copy `.env.example` to `.env.local` and configure your backend endpoints:

```bash
cp .env.example .env.local
```

Edit `.env.local` to point to your backend:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
```

See `.env.example` for all available configuration options.

## Development

### Prerequisites: Starting the Backend Service

Before running the frontend development server, you need to start the backend API service. The frontend health check and API calls depend on the backend being available.

**See [`backend/DEVELOPMENT.md`](../backend/DEVELOPMENT.md) for detailed instructions on installing dependencies and starting the backend service.**

Quick start for the backend (from the repository root):

```bash
# Install uvicorn if not already installed
python3 -m pip install "uvicorn[standard]"

# Start the backend API server
uvicorn kyrgame.webapp:create_app --app-dir backend --factory --reload --host 0.0.0.0 --port 8000
```

The backend will be available at `http://localhost:8000`.

### Run the Development Server

Once the backend is running, start the frontend development server:

```bash
npm run dev
```

This starts the Vite development server with hot module replacement (HMR). The application will be available at `http://localhost:5173` by default.

### Build for Production

```bash
npm run build
```

Outputs optimized static files to the `dist/` directory.

### Preview Production Build

```bash
npm run preview
```

Serves the production build locally for testing.

## Testing

### Run Tests

```bash
npm test
```

Runs the Vitest test suite in watch mode.

### Run Tests Once

```bash
npm run test:ci
```

Runs the test suite once and exits (useful for CI/CD pipelines).

## Code Quality

### Linting

```bash
npm run lint
```

Runs ESLint to check for code style and quality issues.

### Formatting

```bash
npm run format
```

Runs Prettier to format all code files according to the project style guide.

## Backend API Connection

The frontend connects to the backend API using endpoints configured via environment variables:

- **HTTP API**: Used for RESTful requests (e.g., `/world/locations`, `/auth/session`)
- **WebSocket**: Used for real-time room broadcasts (future feature)

The health check page validates that the backend is reachable by fetching the location catalog at startup. If the backend is unavailable or returns an error, the UI displays diagnostic information.

## Project Structure

```
frontend/
├── public/          # Static assets
├── src/
│   ├── assets/      # Images, fonts, etc.
│   ├── config/      # Configuration modules (endpoints, etc.)
│   ├── pages/       # React page components
│   ├── App.tsx      # Root application component
│   ├── App.css      # Application styles
│   └── main.tsx     # Application entry point
├── .env.example     # Example environment configuration
├── index.html       # HTML entry point
├── package.json     # Dependencies and scripts
├── tsconfig.json    # TypeScript configuration
└── vite.config.ts   # Vite configuration
```

## Technology Stack

- **Vite**: Build tool and development server
- **React**: UI library
- **TypeScript**: Type-safe JavaScript
- **Vitest**: Unit testing framework
- **ESLint**: Code linting
- **Prettier**: Code formatting
