# Design system

## Direction

Mood: “quiet desktop darkroom — precise controls on a clean workbench”. The interface is light, task-first, and compact. Indigo is reserved for focus and the primary action; cyan marks successful device-template recognition.

## Palette

Restrained strategy, expressed only in OKLCH.

```css
--bg: oklch(1 0 0);
--surface: oklch(0.965 0.004 270);
--ink: oklch(0.205 0.022 270);
--muted: oklch(0.49 0.025 270);
--line: oklch(0.885 0.008 270);
--primary: oklch(0.45 0.18 270);
--primary-hover: oklch(0.39 0.17 270);
--accent: oklch(0.69 0.135 205);
--danger: oklch(0.53 0.19 28);
```

## Typography and spacing

- System UI sans-serif; no external font download.
- Body 15–16px, title responsive 30–44px, line height 1.5.
- Spacing follows a 4px base. Main content width is capped at 1120px.

## Components

- File selectors are numbered horizontal rows with a native file input and selected filename.
- Primary button is solid indigo with white text; secondary controls remain neutral.
- Advanced settings use native `details` semantics.
- Status is a live region with icon, title, and concise message.
- Corners are modest (8–12px), shadows are nearly absent, and panels use borders for structure.

## Responsive behavior

- At wide widths, inputs and the status/guide panel form a 2:1 grid.
- Below 800px, content becomes one column.
- Touch targets remain at least 44px and filenames truncate without breaking layout.
