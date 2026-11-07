import { Badge } from '@/components/ui/badge';
import { COMING_SOON } from '@/lib/navigation';
import { cn } from '@/lib/utils';

// SVG children scale and turn about their own box, not the drawing's corner.
const OWN_BOX = '[transform-box:fill-box]';

/** A four-pointed sparkle centred on (x, y). */
function Sparkle({ x, y, size = 1, className, delay = '0s' }) {
  return (
    <path
      d="M0 -8C1 -2 2 -1 8 0C2 1 1 2 0 8C-1 2 -2 1 -8 0C-2 -1 -1 -2 0 -8Z"
      transform={`translate(${x} ${y}) scale(${size})`}
      className={cn('motion-safe:animate-twinkle origin-center', OWN_BOX, className)}
      style={{ animationDelay: delay }}
    />
  );
}

/** A chart still filling in: the sales to come. */
function SalesChip() {
  return (
    <>
      <rect x="30" y="112" width="62" height="48" rx="10" strokeWidth="1.5" className="fill-card stroke-border" />
      <rect x="42" y="138" width="8" height="12" rx="2" className="fill-muted-foreground/30" />
      <rect x="56" y="130" width="8" height="20" rx="2" className="fill-muted-foreground/50" />
      <rect x="70" y="122" width="8" height="28" rx="2" className="fill-highlight" />
    </>
  );
}

/** Three plans, one picked: the plans and prices to come. */
function PlansChip() {
  return (
    <>
      <rect x="30" y="112" width="62" height="48" rx="10" strokeWidth="1.5" className="fill-card stroke-border" />
      <rect x="40" y="121" width="42" height="7" rx="3.5" className="fill-muted-foreground/30" />
      <rect x="40" y="132.5" width="42" height="7" rx="3.5" className="fill-highlight" />
      <rect x="40" y="144" width="42" height="7" rx="3.5" className="fill-muted-foreground/30" />
    </>
  );
}

const CHIPS = { sales: SalesChip, plans: PlansChip };

/**
 * The Hub's "being built" mascot: an owl in round glasses and the logo's
 * graduation cap, peering over a laptop, with a few sparkles and a card of the
 * module to come (`variant`: a chart filling in for sales, plans for pricing).
 * Drawn in the theme's neutrals with the logo's yellow, so it suits light and
 * dark alike; it only moves for readers who have not asked for reduced motion.
 * Purely decorative: the page around it says what is coming.
 */
function BuildingIllustration({ variant, className }) {
  const Chip = CHIPS[variant] ?? SalesChip;
  return (
    <svg viewBox="0 0 320 240" className={className} aria-hidden="true" focusable="false">
      <circle cx="160" cy="130" r="98" className="fill-highlight/20 dark:fill-highlight/10" />
      <circle
        cx="160"
        cy="130"
        r="114"
        fill="none"
        strokeWidth="1.5"
        strokeDasharray="3 7"
        strokeLinecap="round"
        className="stroke-highlight/70"
      />

      <Sparkle x={58} y={62} size={1.1} className="fill-highlight" />
      <Sparkle x={268} y={170} size={0.9} className="fill-muted-foreground/50" delay="0.8s" />
      <Sparkle x={250} y={46} size={0.7} className="fill-highlight" delay="1.6s" />
      <Sparkle x={74} y={196} size={0.6} className="fill-muted-foreground/50" delay="1.2s" />

      <g className="motion-safe:animate-float" style={{ animationDelay: '1s' }}>
        <Chip />
      </g>

      <g className="motion-safe:animate-float">
        {/* Body, then the feathered belly. */}
        <ellipse cx="160" cy="146" rx="54" ry="60" strokeWidth="3" className="fill-highlight-foreground stroke-highlight dark:fill-muted" />
        <ellipse cx="160" cy="164" rx="32" ry="34" className="fill-white/10" />
        <path
          d="M146 156q7 6 14 0q7 6 14 0M146 170q7 6 14 0q7 6 14 0"
          fill="none"
          strokeWidth="2"
          strokeLinecap="round"
          className="stroke-highlight/50"
        />

        {/* Eyes behind round glasses; they blink now and then. */}
        <g className={cn('motion-safe:animate-blink origin-center', OWN_BOX)}>
          <circle cx="140" cy="126" r="17" className="fill-white" />
          <circle cx="180" cy="126" r="17" className="fill-white" />
          <circle cx="143" cy="128" r="8" className="fill-highlight-foreground" />
          <circle cx="183" cy="128" r="8" className="fill-highlight-foreground" />
          <circle cx="146" cy="125" r="2.5" className="fill-white" />
          <circle cx="186" cy="125" r="2.5" className="fill-white" />
        </g>
        <g fill="none" strokeWidth="3" className="stroke-highlight">
          <circle cx="140" cy="126" r="20" />
          <circle cx="180" cy="126" r="20" />
          <path d="M156 124q4 -3 8 0" strokeLinecap="round" />
        </g>
        <path d="M153 142L160 154L167 142L160 137Z" className="fill-highlight" />

        {/* The logo's graduation cap, its tassel swinging. */}
        <path d="M138 90v12q22 12 44 0v-12" strokeWidth="2.5" className="fill-highlight-foreground stroke-highlight dark:fill-muted" />
        <path
          d="M114 84L160 66L206 84L160 102Z"
          strokeWidth="2.5"
          strokeLinejoin="round"
          className="fill-highlight-foreground stroke-highlight dark:fill-muted"
        />
        <g className={cn('motion-safe:animate-sway origin-top', OWN_BOX)}>
          <path d="M160 84L198 90V110" fill="none" strokeWidth="2.5" strokeLinecap="round" className="stroke-highlight" />
          <circle cx="198" cy="113" r="4.5" className="fill-highlight" />
        </g>

        {/* Peering over the laptop, wings on its lid. */}
        <rect x="104" y="164" width="112" height="62" rx="9" className="fill-foreground/85" />
        <circle cx="160" cy="195" r="7" className="fill-highlight" />
        <rect x="92" y="224" width="136" height="7" rx="3.5" className="fill-muted-foreground/40" />
        <ellipse cx="118" cy="165" rx="14" ry="7" strokeWidth="2.5" className="fill-highlight-foreground stroke-highlight dark:fill-muted" />
        <ellipse cx="202" cy="165" rx="14" ry="7" strokeWidth="2.5" className="fill-highlight-foreground stroke-highlight dark:fill-muted" />
      </g>
    </svg>
  );
}

/**
 * A module that is on the way: what it will be for, the mascot at work on it,
 * and somewhere useful to go meanwhile (`action`). `icon` names the module and
 * `variant` (sales, plans) the card beside the mascot. Nothing on it acts on
 * data: the module's business logic does not exist yet.
 */
export function ComingSoon({ icon: Icon, title, description, action, variant }) {
  return (
    <section
      aria-labelledby="coming-soon-title"
      className="bg-card flex flex-col items-center overflow-hidden rounded-xl border px-6 py-12 text-center sm:py-16"
    >
      <div className="relative w-full max-w-sm">
        <BuildingIllustration variant={variant} className="w-full" />
        {Icon ? (
          <span
            aria-hidden="true"
            className="bg-card text-foreground motion-safe:animate-float absolute top-[8%] right-[2%] flex size-12 items-center justify-center rounded-xl border shadow-sm [animation-delay:0.5s]"
          >
            <Icon className="size-6" />
          </span>
        ) : null}
      </div>
      <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
        <h1 id="coming-soon-title" className="text-2xl font-semibold tracking-tight">
          {title}
        </h1>
        <Badge variant="highlight">{COMING_SOON}</Badge>
      </div>
      {description ? (
        <p className="text-muted-foreground mt-2 max-w-md text-sm text-pretty sm:text-base">{description}</p>
      ) : null}
      <p className="text-muted-foreground/80 mt-1 text-xs">We are building this now. It will appear here when it is ready.</p>
      {action ? <div className="mt-6">{action}</div> : null}
    </section>
  );
}
