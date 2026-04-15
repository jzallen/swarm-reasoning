import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { VerdictDisplay } from './VerdictDisplay';
import { makeVerdict, makeCitation } from '@/test/fixtures';

describe('VerdictDisplay', () => {
  it('renders the factuality score formatted to 2 decimals', () => {
    render(<VerdictDisplay verdict={makeVerdict({ factualityScore: 0.8 })} />);
    expect(screen.getByText('0.80')).toBeInTheDocument();
  });

  it('renders the rating label text', () => {
    render(<VerdictDisplay verdict={makeVerdict({ ratingLabel: 'pants-on-fire' })} />);
    expect(screen.getByText('Pants on Fire')).toBeInTheDocument();
  });

  it('renders the narrative', () => {
    const narrative = 'This claim lacks supporting evidence.';
    render(<VerdictDisplay verdict={makeVerdict({ narrative })} />);
    expect(screen.getByText(narrative)).toBeInTheDocument();
  });

  it('renders the signal count', () => {
    render(<VerdictDisplay verdict={makeVerdict({ signalCount: 37 })} />);
    expect(screen.getByText(/37 signals from 11 agents/)).toBeInTheDocument();
  });

  it('renders the citation table when citations exist', () => {
    const verdict = makeVerdict({ citations: [makeCitation({ sourceName: 'AP News' })] });
    render(<VerdictDisplay verdict={verdict} />);
    expect(screen.getByText('AP News')).toBeInTheDocument();
  });

  it('does not render the citation table when citations are empty', () => {
    const verdict = makeVerdict({ citations: [] });
    render(<VerdictDisplay verdict={verdict} />);
    expect(screen.queryByText('Source')).not.toBeInTheDocument();
  });

  it('renders the print button', () => {
    render(<VerdictDisplay verdict={makeVerdict()} />);
    expect(screen.getByRole('button', { name: 'Print' })).toBeInTheDocument();
  });

  it('maps all rating labels correctly', () => {
    const cases: Array<[string, string]> = [
      ['true', 'True'],
      ['mostly-true', 'Mostly True'],
      ['half-true', 'Half True'],
      ['mostly-false', 'Mostly False'],
      ['false', 'False'],
      ['pants-on-fire', 'Pants on Fire'],
    ];

    for (const [label, expected] of cases) {
      const { unmount } = render(
        <VerdictDisplay verdict={makeVerdict({ ratingLabel: label as never })} />,
      );
      expect(screen.getByText(expected)).toBeInTheDocument();
      unmount();
    }
  });
});
