// Renders the real Hub App at a path, as a caller whose API answers come from
// fixtures.json (api-stub.js), and describes what that caller is offered:
// where they end up, the sidebar, and the page's buttons, links, column
// headers, tabs, filters and row-menu items.
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import App from '@/App';

const NO_ACCESS = "Your access isn't set up yet";

async function settle(rounds = 10) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
const label = (element) => clean(element.textContent) || clean(element.getAttribute('aria-label')) || clean(element.getAttribute('title'));
const uniqueSorted = (values) => [...new Set(values.filter(Boolean))].sort();

function newBodyChildren(before) {
  return [...document.body.children].filter((child) => !before.has(child));
}

async function press(element, key) {
  await act(async () => {
    element.dispatchEvent(new window.KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
  });
  await settle(3);
}

async function click(element) {
  await act(async () => {
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
  });
  await settle(3);
}

// Open every row menu in turn and note what it offers.
async function rowMenus(content) {
  const menus = [];
  for (const trigger of content.querySelectorAll('button[aria-haspopup="menu"]')) {
    const before = new Set(document.body.children);
    await press(trigger, 'Enter');
    const items = newBodyChildren(before).flatMap((node) => [...node.querySelectorAll('[role="menuitem"]')].map(label));
    menus.push(uniqueSorted(items).join(' | '));
    if (document.activeElement) await press(document.activeElement, 'Escape');
  }
  for (const trigger of content.querySelectorAll('button[aria-label="Row actions"]')) {
    const before = new Set(document.body.children);
    await click(trigger);
    // React owns the menu's portal and removes it on unmount.
    const items = newBodyChildren(before).flatMap((node) => [...node.querySelectorAll('button')].map(label));
    menus.push(uniqueSorted(items).join(' | '));
  }
  return uniqueSorted(menus);
}

export async function describeAt(path, setup) {
  globalThis.__hubAccess = { ...setup, calls: [] };
  window.history.replaceState(null, '', path);
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<App />);
  });
  await settle();

  const content = container.querySelector('[data-slot="sidebar-inset"]') || container;
  const result = {
    at: window.location.pathname + window.location.search,
    noAccess: clean(container.textContent).includes(NO_ACCESS),
    nav: [...container.querySelectorAll('[data-sidebar="menu"] a')].map((a) => a.getAttribute('href')),
    buttons: uniqueSorted([...content.querySelectorAll('button')].map(label)),
    links: uniqueSorted([...content.querySelectorAll('a[href]')].map((a) => a.getAttribute('href'))),
    headers: uniqueSorted([...content.querySelectorAll('th')].map(label)),
    tabs: uniqueSorted([...content.querySelectorAll('[role="tab"]')].map(label)),
    filters: uniqueSorted([...content.querySelectorAll('[role="combobox"], select')].map(
      (el) => clean(el.getAttribute('aria-label')) || clean(el.getAttribute('name')) || label(el),
    )),
    menus: await rowMenus(content),
    calls: uniqueSorted(globalThis.__hubAccess.calls),
  };

  await act(async () => root.unmount());
  container.remove();
  // Whatever React did not own (focus guards and the like) goes too.
  for (const node of [...document.body.children]) {
    if (node.parentNode === document.body) document.body.removeChild(node);
  }
  return result;
}
