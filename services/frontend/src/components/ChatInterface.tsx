import { useState, useRef, useEffect } from 'react';
import type { ProgressEvent } from '@/api/types';
import type { SessionPhase } from '@/hooks/useSession';
import { ProgressBubble } from './ProgressBubble';
import styles from './ChatInterface.module.css';

interface ChatInterfaceProps {
  phase: SessionPhase;
  claim: string | null;
  events: ProgressEvent[];
  onSubmit: (claimText: string) => void;
}

export function ChatInterface({ phase, claim, events, onSubmit }: ChatInterfaceProps) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const isSubmitting = phase !== 'idle';

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events.length, claim]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || isSubmitting) return;
    onSubmit(text);
    setInput('');
  };

  return (
    <div className={styles.container}>
      <div className={styles.messages}>
        {claim && (
          <div className={styles.userBubble}>
            <p className={styles.userText}>{claim}</p>
          </div>
        )}

        {claim && events.length === 0 && phase === 'active' && (
          <div className={styles.systemBubble}>
            <p className={styles.connectingText}>Connecting to agents...</p>
          </div>
        )}

        {events.map((event, i) => (
          <ProgressBubble key={`${event.agent}-${event.timestamp}-${i}`} event={event} />
        ))}

        <div ref={messagesEndRef} />
      </div>

      <form className={styles.inputArea} onSubmit={handleSubmit}>
        <textarea
          className={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Enter a claim to fact-check..."
          disabled={isSubmitting}
          rows={2}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSubmit(e);
            }
          }}
        />
        <button
          className={styles.submitBtn}
          type="submit"
          disabled={isSubmitting || !input.trim()}
        >
          {phase === 'creating' ? 'Submitting...' : 'Check Claim'}
        </button>
      </form>
    </div>
  );
}
