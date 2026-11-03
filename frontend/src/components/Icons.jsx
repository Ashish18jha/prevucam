const P = {
  dashboard: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
  live: "M15 10l5-3v10l-5-3M3 6h12v12H3z",
  events: "M4 6h16M4 12h16M4 18h10",
  zones: "M4 4l7 3 9-3v16l-9 3-7-3V4zm7 3v16",
  detect: "M12 3v3m0 12v3M3 12h3m12 0h3M7 7l2 2m6 6l2 2M17 7l-2 2m-6 6l-2 2M12 9a3 3 0 100 6 3 3 0 000-6z",
  camera: "M4 8h3l2-3h6l2 3h3v11H4zM12 11a3 3 0 100 6 3 3 0 000-6z",
  bell: "M6 16V11a6 6 0 1112 0v5l2 2H4l2-2zm4 4h4",
  report: "M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6",
  scan: "M4 8V5a1 1 0 011-1h3M16 4h3a1 1 0 011 1v3M20 16v3a1 1 0 01-1 1h-3M8 20H5a1 1 0 01-1-1v-3M10 9l5 3-5 3z",
  film: "M4 4h16v16H4zM8 4v16M16 4v16M4 8h4m8 0h4M4 16h4m8 0h4M4 12h16",
  settings: "M12 9a3 3 0 100 6 3 3 0 000-6zm7.4 3a7.4 7.4 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 00-2-1.2L14.5 3h-5l-.4 2.6a7 7 0 00-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 000 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 002 1.2l.4 2.6h5l.4-2.6a7 7 0 002-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  restart: "M4 12a8 8 0 1 0 2.3-5.6M4 4v5h5",
  download: "M12 3v12m0 0l-5-5m5 5l5-5M4 21h16",
  trash: "M4 7h16M9 7V4h6v3m-8 0l1 13h8l1-13",
  send: "M3 11l18-8-8 18-2-8-8-2z",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  upload: "M12 16V4m0 0L7 9m5-5l5 5M4 20h16",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  back: "M15 5l-7 7 7 7",
  plus: "M12 5v14M5 12h14",
  check: "M5 12l5 5L20 7",
  search: "M11 4a7 7 0 100 14 7 7 0 000-14zm9 16l-4-4",
  x: "M6 6l12 12M18 6L6 18",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12zm10-3a3 3 0 100 6 3 3 0 000-6z",
  off: "M3 3l18 18M10 5h5l2 3h3v9M4 8h2m0 0v11h12",
};

export default function Icon({ name, size, ...rest }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
      strokeLinejoin="round" width={size} height={size} aria-hidden="true" {...rest}>
      <path d={P[name] || ""} />
    </svg>
  );
}
