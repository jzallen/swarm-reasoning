import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SnapshotView } from './SnapshotView';

describe('SnapshotView', () => {
  it('renders expired message when isExpired is true', () => {
    render(<SnapshotView snapshotUrl={null} isExpired />);
    expect(screen.getByText(/expired.*3 days/i)).toBeInTheDocument();
  });

  it('renders fallback message when snapshotUrl is null and not expired', () => {
    render(<SnapshotView snapshotUrl={null} />);
    expect(screen.getByText(/not yet available/i)).toBeInTheDocument();
  });

  it('renders an iframe with the snapshot URL', () => {
    render(<SnapshotView snapshotUrl="https://cdn.example.com/snap.html" />);

    const iframe = document.querySelector('iframe');
    expect(iframe).toBeTruthy();
    expect(iframe!.src).toBe('https://cdn.example.com/snap.html');
    expect(iframe!.title).toBe('Session snapshot');
  });

  it('renders PrintButton when snapshot is available', () => {
    render(<SnapshotView snapshotUrl="https://cdn.example.com/snap.html" />);
    expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument();
  });
});
