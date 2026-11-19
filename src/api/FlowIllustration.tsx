import { useId } from 'react';

/** Decorative adaptation of ai-portfolio's branching-agent motion motif. */
export function FlowIllustration({ compact = false }: { compact?: boolean }) {
  const id = useId();
  return (
    <div
      className={`flow-illustration ${compact ? 'flow-illustration-compact' : ''}`}
      aria-hidden="true"
    >
      <svg viewBox="0 0 460 250" focusable="false">
        <defs>
          <pattern id={`${id}-grid`} width="22" height="22" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" className="flow-grid-dot" />
          </pattern>
          <linearGradient id={`${id}-wash`} x2="1" y2="1">
            <stop stopColor="var(--primary-soft)" />
            <stop offset="1" stopColor="var(--surface)" />
          </linearGradient>
        </defs>
        <rect x="10" y="10" width="440" height="230" rx="28" fill={`url(#${id}-wash)`} />
        <rect x="10" y="10" width="440" height="230" rx="28" fill={`url(#${id}-grid)`} />
        <ellipse cx="230" cy="220" rx="170" ry="9" className="flow-shadow" />
        <g className="flow-wires">
          <path d="M96 132H150M212 132H237Q250 132 250 118V77Q250 63 264 63H291M212 132H237Q250 132 250 147V179Q250 193 264 193H291M345 63H360Q374 63 374 78V118Q374 132 388 132M345 193H360Q374 193 374 178V147Q374 132 388 132" />
          <path
            className="flow-signal"
            d="M96 132H150M212 132H237Q250 132 250 118V77Q250 63 264 63H291M345 63H360Q374 63 374 78V118Q374 132 388 132"
          />
        </g>
        <g className="flow-module">
          <rect x="36" y="100" width="60" height="64" rx="14" />
          <rect x="48" y="91" width="60" height="64" rx="14" className="flow-offset" />
          <path d="M63 109H91M63 118H85M63 127H87" className="flow-glyph" />
          <text x="78" y="145">
            INPUT
          </text>
        </g>
        <g className="flow-module flow-module-main">
          <rect x="150" y="100" width="66" height="64" rx="17" />
          <rect x="158" y="91" width="66" height="64" rx="17" className="flow-offset" />
          <path
            d="M191 106V124M180 115H202M183 108L199 122M183 122L199 108"
            className="flow-glyph"
          />
          <text x="191" y="144">
            ROUTE
          </text>
        </g>
        <g className="flow-module">
          <rect x="286" y="39" width="65" height="54" rx="13" />
          <path
            d="M302 53L296 59L302 65M333 53L339 59L333 65M322 51L314 67"
            className="flow-glyph"
          />
          <text x="318" y="83">
            TOOLS
          </text>
          <rect x="286" y="167" width="65" height="54" rx="13" />
          <circle cx="309" cy="183" r="3" className="flow-dot" />
          <circle cx="326" cy="183" r="3" className="flow-dot" />
          <path d="M309 188V196H326V188" className="flow-glyph" />
          <text x="318" y="212">
            MERGE
          </text>
        </g>
        <g className="flow-module">
          <rect x="387" y="103" width="49" height="60" rx="12" />
          <path d="M400 116H422M400 124H419M400 132H414" className="flow-glyph" />
          <text x="411" y="153">
            OUT
          </text>
        </g>
        <circle cx="125" cy="132" r="4" className="flow-dot" />
        <circle cx="251" cy="102" r="4" className="flow-dot" />
        <circle cx="374" cy="102" r="4" className="flow-dot" />
        <g className="flow-caption">
          <text x="38" y="33">
            A CONNECTED WAY TO BUILD
          </text>
        </g>
      </svg>
    </div>
  );
}
