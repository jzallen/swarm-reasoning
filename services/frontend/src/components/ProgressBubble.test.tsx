import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ProgressBubble } from './ProgressBubble';
import { makeProgressEvent } from '@/test/fixtures';

describe('ProgressBubble', () => {
  it('renders agent name and message', () => {
    const event = makeProgressEvent({
      agent: 'claim-detector',
      message: 'Analyzing claim structure',
    });
    render(<ProgressBubble event={event} />);

    expect(screen.getByText('claim-detector')).toBeInTheDocument();
    expect(screen.getByText('Analyzing claim structure')).toBeInTheDocument();
  });

  it('renders the phase label', () => {
    const event = makeProgressEvent({ phase: 'fanout' });
    render(<ProgressBubble event={event} />);

    expect(screen.getByText('Fanout')).toBeInTheDocument();
  });

  it('renders a formatted timestamp', () => {
    const event = makeProgressEvent({ timestamp: '2026-04-13T14:30:45Z' });
    render(<ProgressBubble event={event} />);

    // The exact format depends on locale; just verify a time string is present
    const timeEl = document.querySelector('[class*="time"]');
    expect(timeEl).toBeTruthy();
    expect(timeEl!.textContent).toMatch(/\d{1,2}:\d{2}:\d{2}/);
  });

  it('applies lifecycle class for agent-started events', () => {
    const event = makeProgressEvent({ type: 'agent-started' });
    const { container } = render(<ProgressBubble event={event} />);

    const bubble = container.firstChild as HTMLElement;
    expect(bubble.className).toContain('lifecycle');
  });

  it('applies lifecycle class for agent-completed events', () => {
    const event = makeProgressEvent({ type: 'agent-completed' });
    const { container } = render(<ProgressBubble event={event} />);

    const bubble = container.firstChild as HTMLElement;
    expect(bubble.className).toContain('lifecycle');
  });

  it('does not apply lifecycle class for agent-progress events', () => {
    const event = makeProgressEvent({ type: 'agent-progress' });
    const { container } = render(<ProgressBubble event={event} />);

    const bubble = container.firstChild as HTMLElement;
    expect(bubble.className).not.toContain('lifecycle');
  });
});
