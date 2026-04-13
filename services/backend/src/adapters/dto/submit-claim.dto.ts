import {
  IsString,
  IsOptional,
  MaxLength,
  IsNotEmpty,
  IsUrl,
  IsDateString,
} from 'class-validator';

export class SubmitClaimDto {
  @IsString()
  @IsNotEmpty()
  @MaxLength(2000)
  claimText!: string;

  @IsOptional()
  @IsUrl()
  sourceUrl?: string;

  @IsOptional()
  @IsDateString()
  sourceDate?: string;
}
