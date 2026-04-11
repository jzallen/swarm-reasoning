import { Claim } from '../value-objects/claim';

describe('Claim', () => {
  it('should create a valid claim', () => {
    const claim = new Claim({ claimText: 'Test claim' });
    expect(claim.claimText).toBe('Test claim');
  });

  it('should trim whitespace', () => {
    const claim = new Claim({ claimText: '  Test claim  ' });
    expect(claim.claimText).toBe('Test claim');
  });

  it('should reject empty text', () => {
    expect(() => new Claim({ claimText: '' })).toThrow(
      'Claim text cannot be empty',
    );
  });

  it('should reject whitespace-only text', () => {
    expect(() => new Claim({ claimText: '   ' })).toThrow(
      'Claim text cannot be empty',
    );
  });

  it('should reject text exceeding max length', () => {
    const longText = 'a'.repeat(2001);
    expect(() => new Claim({ claimText: longText })).toThrow(
      'exceeds maximum length',
    );
  });

  it('should accept text at max length', () => {
    const maxText = 'a'.repeat(2000);
    const claim = new Claim({ claimText: maxText });
    expect(claim.claimText).toBe(maxText);
  });

  it('should accept optional sourceUrl and sourceDate', () => {
    const claim = new Claim({
      claimText: 'Test',
      sourceUrl: 'https://example.com',
      sourceDate: '2024-01-01',
    });
    expect(claim.sourceUrl).toBe('https://example.com');
    expect(claim.sourceDate).toBe('2024-01-01');
  });
});
