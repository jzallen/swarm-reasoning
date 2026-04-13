import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CitationTable } from './CitationTable';
import { makeCitation } from '@/test/fixtures';

describe('CitationTable', () => {
  it('renders table headers', () => {
    render(<CitationTable citations={[makeCitation()]} />);

    expect(screen.getByText('Source')).toBeInTheDocument();
    expect(screen.getByText('URL')).toBeInTheDocument();
    expect(screen.getByText('Agent')).toBeInTheDocument();
    expect(screen.getByText('Code')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Cited By')).toBeInTheDocument();
  });

  it('renders citation data', () => {
    const citation = makeCitation({
      sourceName: 'Reuters',
      agent: 'coverage-center',
      observationCode: 'CVG-002',
      convergenceCount: 5,
    });
    render(<CitationTable citations={[citation]} />);

    expect(screen.getByText('Reuters')).toBeInTheDocument();
    expect(screen.getByText('coverage-center')).toBeInTheDocument();
    expect(screen.getByText('CVG-002')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('sorts citations by convergenceCount descending', () => {
    const citations = [
      makeCitation({ sourceName: 'Low', convergenceCount: 1 }),
      makeCitation({ sourceName: 'High', convergenceCount: 10 }),
      makeCitation({ sourceName: 'Mid', convergenceCount: 5 }),
    ];
    render(<CitationTable citations={citations} />);

    const rows = screen.getAllByRole('row');
    // First row is header, data rows follow
    const cells = rows.slice(1).map((row) => row.querySelector('td')!.textContent);
    expect(cells).toEqual(['High', 'Mid', 'Low']);
  });

  it('truncates long URLs', () => {
    const longUrl = 'https://example.com/very/long/path/that/exceeds/forty/characters/in/total';
    const citation = makeCitation({ sourceUrl: longUrl });
    render(<CitationTable citations={[citation]} />);

    const link = screen.getByRole('link');
    expect(link.textContent!.length).toBeLessThanOrEqual(40);
    expect(link.textContent).toContain('\u2026');
  });

  it('does not truncate short URLs', () => {
    const shortUrl = 'https://example.com/short';
    const citation = makeCitation({ sourceUrl: shortUrl });
    render(<CitationTable citations={[citation]} />);

    const link = screen.getByRole('link');
    expect(link.textContent).toBe(shortUrl);
  });

  it('renders links with security attributes', () => {
    render(<CitationTable citations={[makeCitation()]} />);

    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders validation status labels', () => {
    const citations = [
      makeCitation({ validationStatus: 'live', sourceName: 'Live Source' }),
      makeCitation({ validationStatus: 'dead', sourceName: 'Dead Source' }),
      makeCitation({ validationStatus: 'not-validated', sourceName: 'Unvalidated Source' }),
    ];
    render(<CitationTable citations={citations} />);

    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.getByText('Dead')).toBeInTheDocument();
    expect(screen.getByText('Not Validated')).toBeInTheDocument();
  });
});
