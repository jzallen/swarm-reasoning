import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatInterface } from './ChatInterface';
import { makeProgressEvent } from '@/test/fixtures';

describe('ChatInterface', () => {
  const defaultProps = {
    phase: 'idle' as const,
    claim: null,
    events: [],
    onSubmit: vi.fn(),
  };

  it('renders the input textarea and submit button', () => {
    render(<ChatInterface {...defaultProps} />);

    expect(screen.getByPlaceholderText('Enter a claim to fact-check...')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check Claim' })).toBeInTheDocument();
  });

  it('disables textarea and button when phase is not idle', () => {
    render(<ChatInterface {...defaultProps} phase="active" />);

    expect(screen.getByPlaceholderText('Enter a claim to fact-check...')).toBeDisabled();
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('shows "Submitting..." on the button during creating phase', () => {
    render(<ChatInterface {...defaultProps} phase="creating" />);
    expect(screen.getByRole('button', { name: 'Submitting...' })).toBeInTheDocument();
  });

  it('disables submit when input is empty', () => {
    render(<ChatInterface {...defaultProps} />);
    expect(screen.getByRole('button', { name: 'Check Claim' })).toBeDisabled();
  });

  it('calls onSubmit with trimmed text and clears input', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();

    render(<ChatInterface {...defaultProps} onSubmit={onSubmit} />);

    const textarea = screen.getByPlaceholderText('Enter a claim to fact-check...');
    await user.type(textarea, '  The sky is blue  ');
    await user.click(screen.getByRole('button', { name: 'Check Claim' }));

    expect(onSubmit).toHaveBeenCalledWith('The sky is blue');
    expect(textarea).toHaveValue('');
  });

  it('submits on Enter key (without Shift)', async () => {
    const onSubmit = vi.fn();
    const user = userEvent.setup();

    render(<ChatInterface {...defaultProps} onSubmit={onSubmit} />);

    const textarea = screen.getByPlaceholderText('Enter a claim to fact-check...');
    await user.type(textarea, 'Test claim{Enter}');

    expect(onSubmit).toHaveBeenCalledWith('Test claim');
  });

  it('renders the claim as a user bubble', () => {
    render(<ChatInterface {...defaultProps} claim="Vaccines cause autism" />);
    expect(screen.getByText('Vaccines cause autism')).toBeInTheDocument();
  });

  it('shows connecting message when active with no events', () => {
    render(
      <ChatInterface {...defaultProps} phase="active" claim="Some claim" events={[]} />,
    );
    expect(screen.getByText('Connecting to agents...')).toBeInTheDocument();
  });

  it('shows reconnected notice instead of connecting when reconnected', () => {
    render(
      <ChatInterface {...defaultProps} phase="active" claim="Some claim" events={[]} reconnected />,
    );
    expect(screen.getByText('Reconnected — earlier messages not shown')).toBeInTheDocument();
    expect(screen.queryByText('Connecting to agents...')).not.toBeInTheDocument();
  });

  it('does not show connecting message when events exist', () => {
    render(
      <ChatInterface
        {...defaultProps}
        phase="active"
        claim="Some claim"
        events={[makeProgressEvent()]}
      />,
    );
    expect(screen.queryByText('Connecting to agents...')).not.toBeInTheDocument();
  });

  it('renders progress bubbles for each event', () => {
    const events = [
      makeProgressEvent({ agent: 'ingestion-agent', message: 'Starting ingestion' }),
      makeProgressEvent({ agent: 'claim-detector', message: 'Detecting claims' }),
    ];
    render(<ChatInterface {...defaultProps} claim="A claim" events={events} />);

    expect(screen.getByText('Starting ingestion')).toBeInTheDocument();
    expect(screen.getByText('Detecting claims')).toBeInTheDocument();
  });
});
