import { GraduationCap, Phone, User } from 'lucide-react';
import { Card } from '../ui/card';
import { Button } from '../ui/button';

// Simple custom WhatsApp SVG icon
function WhatsappIcon(props) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  );
}

export function MentorCard({ mentorName, mentorEmail, mentorPhone }) {
  if (!mentorName && !mentorEmail) {
    return (
      <Card>
        <h3 className="text-text-secondary mb-3 text-sm font-semibold">
          Your Mentor
        </h3>
        <div className="flex items-center gap-3.5">
          <div className="bg-surface-muted flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
            <User className="text-text-muted h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-text-primary text-sm font-semibold">
              No mentor assigned yet
            </p>
            <p className="text-text-muted text-xs">
              Your mentor will appear here once assigned.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const name = mentorName || mentorEmail;
  const phone = mentorPhone;
  const waLink = phone ? `https://wa.me/${phone.replace(/\D/g, '')}` : null;

  return (
    <Card>
      <h3 className="text-text-secondary mb-3 text-sm font-semibold">
        Your Mentor
      </h3>
      <div className="flex flex-wrap items-center gap-3.5">
        <div className="bg-primary-subtle flex h-10 w-10 shrink-0 items-center justify-center rounded-xl">
          <GraduationCap className="text-primary h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1 basis-28">
          <p className="text-text-primary truncate text-sm font-semibold">
            {name}
          </p>
          <p className="text-text-muted inline-flex items-center gap-1 text-xs">
            <Phone className="h-3 w-3 shrink-0" />
            <span className="truncate">
              {phone ?? 'No phone available'}
            </span>
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          className="ml-auto shrink-0"
          icon={<WhatsappIcon className="h-4 w-4" />}
          disabled={!waLink}
          onClick={() => waLink && window.open(waLink, '_blank')}
        >
          WhatsApp
        </Button>
      </div>
    </Card>
  );
}
