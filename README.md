# Kyrandia Modernization

<pre>
                     __ __                           ___
                    / //_/_  ___________ _____  ____/ (_)___ _
                   / ,< / / / / ___/ __ `/ __ \/ __  / / __ `/
                  / /| / /_/ / /  / /_/ / / / / /_/ / / /_/ /
                 /_/ |_\__, /_/   \__,_/_/ /_/\__,_/_/\__,_/
                      /____/
</pre>

## Overview

Kyrandia began as a MajorBBS/Worldgroup text adventure where apprentices chased the title of "Arch-Mage of Legends." This repository now houses the effort to bring that world to a modern stack: a JavaScript front-end paired with a FastAPI- and SQLAlchemy-powered Python back-end. Our goal is to preserve the cooperative, spell-driven gameplay while delivering a maintainable, testable web experience.

## Project Goals

- Keep gameplay behaviors faithful to the original C sources while exposing them through modern transports (HTTP + WebSockets).
- Treat the legacy data structures as canonical schemas for new models, validation rules, and content serialization.
- Provide a smooth developer workflow with pytest-driven testing, fixture packaging, and Docker/WSL2-friendly tooling.
- Preserve the historical assets by keeping the full Borland/Visual Studio project in `legacy/` for reference and for anyone who still wants to build the classic module.

## Repository Layout

- `backend/` — FastAPI services, SQLAlchemy models, fixtures, and scripts for packaging offline content.
- `frontend/` — Vite + React + TypeScript application providing a view-only navigator UI for exploring game fixtures.
- `docs/` — Porting plan, architecture notes, and code maps that tie legacy concepts to the new stack.
- `legacy/` — The original MajorBBS/Worldgroup sources, assets, and build files (`ELWKYR.MAK`, `elwkyr.vcxproj`, message catalogs, and packaged `Dist/`).
- `LICENSE.txt`, `CONTRIBUTING.txt`, `AGENTS.md` — Policies and contributor guidance that apply across the project.

## Development Workflow

1. **Install backend dependencies**
   - Follow `backend/DEVELOPMENT.md` to create a virtual environment and install requirements.
2. **Install frontend dependencies**
   - Navigate to `frontend/` and run `npm install` to install the Node.js dependencies.
   - Copy `frontend/.env.example` to `frontend/.env.local` and configure your backend endpoints.
3. **Run the development server**
   - Start the backend API server following instructions in `backend/DEVELOPMENT.md`.
   - In a separate terminal, run `cd frontend && npm run dev` to start the frontend development server.
4. **Run tests**
   - Backend: Execute `pytest backend/tests` to validate fixtures, models, and helper utilities.
   - Frontend: Execute `cd frontend && npm test` to run the frontend test suite.
5. **Package offline content**
   - Generate a bundle suitable for disconnected clients with `python -m kyrgame.scripts.package_content --output legacy/Dist/offline-content.json`.
6. **Consult or build the legacy module**
   - The C sources live in `legacy/`. To build the Borland target, run `cd legacy && make -f ELWKYR`. Visual Studio users can open `legacy/elwkyr.vcxproj`.

## Legacy Backstory (for context)

The adventure is set in the enchanted realm of Kyrandia under the eye of Tashanna, the "Lady of Legends." Players begin as young apprentices who explore, trade, duel, and solve puzzles to advance through spellcasting ranks. That spirit of cooperative multiplayer magic continues to guide the modernized experience even as we reimplement the systems behind it.

## License

This project is licensed under the AGPL v3. Additional terms apply to contributions and derivative projects. Please see the LICENSE file for more details.

## Contributing

We welcome contributions from the community. By contributing, you agree to the terms outlined in the CONTRIBUTING file.

## Creating a Fork

If you create an entirely new project based on this work, it must be licensed under the AGPL v3, assign all right, title, and interest, including all copyrights, in and to your fork to Rick Hadsall and Elwynor Technologies, and you must include the additional terms from the LICENSE file in your project's LICENSE file.
