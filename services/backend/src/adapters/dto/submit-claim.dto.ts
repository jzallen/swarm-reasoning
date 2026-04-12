import { IsString, IsOptional, MaxLength, IsNotEmpty } from 'class-validator';

export class SubmitClaimDto {
  @IsString()
  @IsNotEmpty()
  @MaxLength(2000)
  claimText: string;

  @IsOptional()
  @IsString()
  sourceUrl?: string;

  @IsOptional()
  @IsString()
  sourceDate?: string;
}
