import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PrintButton } from './PrintButton';

describe('PrintButton', () => {
  it('renders a button labeled "Print"', () => {
    render(<PrintButton />);
    expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument();
  });

  it('calls window.print when clicked', async () => {
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {});
    render(<PrintButton />);

    await userEvent.click(screen.getByRole('button', { name: 'Print' }));

    expect(printSpy).toHaveBeenCalledOnce();
    printSpy.mockRestore();
  });
});
