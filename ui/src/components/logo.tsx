export function Logo({ className }: { className?: string }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" className={className} aria-hidden="true">
      <path fill="#241f20" d="M10 18.5h28a3 3 0 0 1 3 3V36a4 4 0 0 1-4 4H11a4 4 0 0 1-4-4V21.5a3 3 0 0 1 3-3z" />
      <path fill="#ff6c2c" d="M8.5 18h31a3.5 3.5 0 0 0 0-7H30.2l-1.6-3.2h-9.2L17.8 11H8.5a3.5 3.5 0 0 0 0 7z" />
      <path fill="none" stroke="#ffffff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" d="M24 23.5v9.2M19.2 29.2 24 34l4.8-4.8" />
    </svg>
  )
}
