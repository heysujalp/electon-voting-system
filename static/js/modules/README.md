# ElectON V2 JavaScript Modules

## Architecture

ES Module system with barrel export via `modules/index.js`.

### Modules

| Module | Purpose |
|--------|---------|
| `config.js` | Centralized constants (timeouts, validation limits) |
| `security.js` | CSRF tokens, HTML sanitization, email validation |
| `api.js` | Fetch wrapper with retry, timeout, CSRF |
| `ui.js` | UIManager (notifications), ThemeManager, modals |
| `validation.js` | Form + field validation with visual feedback |
| `state.js` | StateStore (localStorage), FormStateManager, createStore |
| `error-handler.js` | Error handling with notification display |
| `utils.js` | DOM ready, date/URL/storage utilities |
| `lazy-loader.js` | Dynamic module import with caching |

### Page Scripts

| Script | Page |
|--------|------|
| `base.js` | Every page — theme toggle, Django message bridge |
| `voter-login.js` | Voter login form |
| `election_dashboard.js` | Election dashboard interactions |

### Usage

```javascript
// In page scripts:
import { apiPost, showNotification, onDOMReady } from './modules/index.js';

// Or use global window.ElectON namespace for non-module scripts:
window.ElectON.showNotification('Hello', 'success');
```
