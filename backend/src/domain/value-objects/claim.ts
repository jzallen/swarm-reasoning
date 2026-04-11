const MAX_CLAIM_LENGTH = 2000;

export class Claim {
  readonly claimText: string;
  readonly sourceUrl?: string;
  readonly sourceDate?: string;

  constructor(params: {
    claimText: string;
    sourceUrl?: string;
    sourceDate?: string;
  }) {
    if (!params.claimText || params.claimText.trim().length === 0) {
      throw new Error('Claim text cannot be empty');
    }
    if (params.claimText.length > MAX_CLAIM_LENGTH) {
      throw new Error(
        `Claim text exceeds maximum length of ${MAX_CLAIM_LENGTH} characters`,
      );
    }
    this.claimText = params.claimText.trim();
    this.sourceUrl = params.sourceUrl;
    this.sourceDate = params.sourceDate;
  }
}
