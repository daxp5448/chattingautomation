// The official KelvionTech logo assets (frontend/public/kelviontech_*.svg) -- both are
// SVG-wrapped rasters, rendered via plain <img> (not next/image, which disables SVG
// optimization by default) so no next.config changes are needed. `kelviontech_logo.svg`
// bakes its "KELVIONTECH" wordmark + tagline in near-white ink, so it only reads
// correctly on a dark surface (see LogoFull below, used on the Login page's dark brand
// panel). `kelviontech_mark_only.svg` is the ribbon glyph alone, with its own teal
// gradient, and works on any background -- used as the compact brand mark everywhere
// else (sidebar, loading states) paired with a normally-typeset "KelvionTech" wordmark
// so it reads correctly on white too. Neither asset's pixels are modified; both are
// always rendered at their native aspect ratio (explicit width+height below, derived
// from each SVG's own viewBox, so the browser reserves the correct box before it loads
// -- no layout shift, no stretch/squash).

const MARK_RATIO = 710 / 290;
const FULL_RATIO = 1536 / 1024;

export function LogoMark({ size = 32, className = "" }: { size?: number; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return (
    <img
      src="/kelviontech_mark_only.svg"
      alt="KelvionTech"
      width={Math.round(size * MARK_RATIO)}
      height={size}
      className={className}
    />
  );
}

/** Icon + typeset wordmark, for use on white/light surfaces (sidebar header, etc). */
export function LogoLockup({ size = 30, className = "" }: { size?: number; className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <LogoMark size={size} />
      <span className="text-[17px] font-semibold tracking-tight text-slate-900">
        Kelvion<span className="text-primary">Tech</span>
      </span>
    </div>
  );
}

/** The full brand lockup asset (mark + baked-in wordmark + tagline) -- only legible on a
 * dark background, since its text is rendered in light ink. Used once, on Login's brand
 * panel. */
export function LogoFull({ width = 320, className = "" }: { width?: number; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element
  return (
    <img
      src="/kelviontech_logo.svg"
      alt="KelvionTech -- We build what others think"
      width={width}
      height={Math.round(width / FULL_RATIO)}
      className={className}
    />
  );
}
