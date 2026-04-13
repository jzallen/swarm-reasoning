import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorBanner } from './ErrorBanner';

describe('ErrorBanner', () => {
  const defaultProps = {
    message: 'Something went wrong',
    onDismiss: vi.fn(),
    onRetry: vi.fn(),
  };

  it('renders the error message', () => {
    render(<ErrorBanner {...defaultProps} />);
    expect(screen.getByText('Something went wrong')).toBeInTheDocument();
  });

  it('has role="alert" for screen readers', () => {
    render(<ErrorBanner {...defaultProps} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('calls onDismiss when dismiss button is clicked', async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();

    render(<ErrorBanner {...defaultProps} onDismiss={onDismiss} />);
    await user.click(screen.getByRole('button', { name: 'Dismiss' }));

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it('calls onRetry when try again button is clicked', async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();

    render(<ErrorBanner {...defaultProps} onRetry={onRetry} />);
    await user.click(screen.getByRole('button', { name: 'Try again' }));

    expect(onRetry).toHaveBeenCalledOnce();
  });
});
