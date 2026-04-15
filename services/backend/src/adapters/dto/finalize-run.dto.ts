import {
  IsString,
  IsNumber,
  IsOptional,
  IsArray,
  ValidateNested,
  Min,
  Max,
  IsNotEmpty,
} from 'class-validator';
import { Type } from 'class-transformer';

export class CitationDto {
  @IsString()
  @IsNotEmpty()
  sourceUrl!: string;

  @IsString()
  @IsNotEmpty()
  sourceName!: string;

  @IsString()
  @IsNotEmpty()
  agent!: string;

  @IsString()
  @IsNotEmpty()
  observationCode!: string;

  @IsString()
  @IsOptional()
  validationStatus?: string;

  @IsNumber()
  @IsOptional()
  convergenceCount?: number;
}

export class FinalizeRunDto {
  @IsString()
  @IsNotEmpty()
  sessionId!: string;

  @IsString()
  @IsNotEmpty()
  verdict!: string;

  @IsNumber()
  @Min(0)
  @Max(1)
  confidence!: number;

  @IsString()
  @IsNotEmpty()
  narrative!: string;

  @IsString()
  @IsOptional()
  ratingLabel?: string;

  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => CitationDto)
  @IsOptional()
  citations?: CitationDto[];
}
