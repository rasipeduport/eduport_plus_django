# Eduport Plus Hub

The staff app: a React + Vite single-page app on top of the Django API (`backend/`), signed in with a
username and password and Django session cookies.

## Running it

```
cp .env.example .env     # VITE_API_URL and VITE_LEARN_URL; every VITE_* value is public
npm install
npm run dev              # http://localhost:3000
```

| Script | What it does |
|---|---|
| `npm run build` | Production bundle in `dist/` (the Docker image serves it with nginx) |
| `npm run lint` | ESLint (`eslint.config.js`) |
| `npm run test:access` | Access tests: what each kind of account is offered on every page |
| `npm run format` / `format:check` | Prettier (not enforced: no shared config yet) |

## Who sees what

Everything the Hub offers follows the permissions `/api/auth/me/` reports for the signed-in account:
`src/lib/access.js` maps each page to the permissions that open it and names the permissions behind
in-page actions. An account that can open no page gets the No Access screen. The API enforces the same
permissions on every request; the Hub only decides what to offer.

## Access tests

`tests/access/` renders the real app in jsdom for each kind of account, with the API answered from
`fixtures.json` (real responses recorded from the backend's authorization-matrix world), and compares what
each is offered with `baseline.json`. Any intended difference is listed, with the decision behind it, in
`approved-changes.json`. `ACCESS_RECORD=1 npm run test:access` re-records the baseline.
