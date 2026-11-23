export function SkipLink() {
  return (
    <a
      href="#main"
      className="fixed top-2 left-2 z-[100] -translate-y-16 print:hidden rounded-md bg-primary px-3 py-2 text-[13px] font-medium text-on-primary focus:translate-y-0 focus:no-underline"
    >
      Skip to content
    </a>
  );
}
