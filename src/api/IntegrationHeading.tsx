import { Braces, Cpu } from 'lucide-react';
import { siGithub, siGmail } from 'simple-icons';

export function IntegrationHeading({ service }: { service: 'gmail' | 'github' | 'groq' | 'http' }) {
  const labels = { gmail: 'Gmail', github: 'GitHub', groq: 'Groq', http: 'HTTP connections' };
  const brand = service === 'gmail' ? siGmail : service === 'github' ? siGithub : null;
  return (
    <div className="integration-heading">
      <span className={`integration-icon integration-icon--${service}`} aria-hidden="true">
        {brand ? (
          <svg viewBox="0 0 24 24" focusable="false">
            <path d={brand.path} fill="currentColor" />
          </svg>
        ) : service === 'groq' ? (
          <Cpu size={22} />
        ) : (
          <Braces size={22} />
        )}
      </span>
      <h2>{labels[service]}</h2>
    </div>
  );
}
