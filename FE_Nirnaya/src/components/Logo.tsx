import React from 'react';

interface LogoProps {
  size?: number;
  showText?: boolean;
  showSubtitle?: boolean;
  className?: string;
}

export const LogoEmblem: React.FC<{ size?: number; className?: string }> = ({ size = 34, className = '' }) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Nirnaya Logo"
    >
      <defs>
        <linearGradient id="nirnaya-grad-primary" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#6366F1" />
          <stop offset="50%" stopColor="#4F46E5" />
          <stop offset="100%" stopColor="#0EA5E9" />
        </linearGradient>
        <linearGradient id="nirnaya-grad-glow" x1="12" y1="12" x2="36" y2="36" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#818CF8" />
          <stop offset="100%" stopColor="#38BDF8" />
        </linearGradient>
      </defs>

      {/* Hexagonal Outer Lattice (Decision Matrix) */}
      <polygon
        points="24,4 42,14 42,34 24,44 6,34 6,14"
        stroke="url(#nirnaya-grad-primary)"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="rgba(15, 23, 42, 0.8)"
      />

      {/* Inner Dynamic Facets Converging at Core Decision */}
      <polygon
        points="24,11 36,18 36,30 24,37 12,30 12,18"
        stroke="url(#nirnaya-grad-glow)"
        strokeWidth="1.8"
        strokeDasharray="1 1"
        fill="rgba(99, 102, 241, 0.12)"
      />

      {/* Central Decision Nexus (The "N" Node) */}
      <path
        d="M17 31V17L31 31V17"
        stroke="url(#nirnaya-grad-primary)"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Decision Point Sparks */}
      <circle cx="17" cy="17" r="2.5" fill="#38BDF8" />
      <circle cx="31" cy="17" r="2.5" fill="#A5B4FC" />
      <circle cx="24" cy="24" r="2" fill="#FFFFFF" />
      <circle cx="17" cy="31" r="2.5" fill="#6366F1" />
      <circle cx="31" cy="31" r="2.5" fill="#06B6D4" />
    </svg>
  );
};

export const NirnayaLogo: React.FC<LogoProps> = ({
  size = 36,
  showText = true,
  showSubtitle = true,
  className = '',
}) => {
  return (
    <div className={`brand-wrapper ${className}`}>
      <div className="brand-logo-glow">
        <LogoEmblem size={size} />
      </div>

      {showText && (
        <div className="brand-info">
          <div className="brand-title-row">
            <span className="brand-name">Nirnaya</span>
            <span className="brand-kannada" title="ನಿರ್ಣಯ (Nirnaya) = 'Decision' in Kannada">
              ನಿರ್ಣಯ
            </span>
          </div>
          {showSubtitle && (
            <span className="brand-tagline">Decision Intelligence</span>
          )}
        </div>
      )}
    </div>
  );
};
