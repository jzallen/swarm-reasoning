import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import {
  S3Client,
  PutObjectCommand,
  DeleteObjectCommand,
  HeadObjectCommand,
} from '@aws-sdk/client-s3';
import type { SnapshotStore } from '@app/interfaces/snapshot-store.interface.js';

@Injectable()
export class S3SnapshotStore implements SnapshotStore {
  private readonly logger = new Logger(S3SnapshotStore.name);
  private readonly s3: S3Client;
  private readonly bucket: string;
  private readonly cloudfrontDomain: string;

  constructor(private readonly configService: ConfigService) {
    this.s3 = new S3Client({
      region: this.configService.get<string>('AWS_REGION', 'us-east-1'),
    });
    this.bucket = this.configService.get<string>('S3_BUCKET', '');
    this.cloudfrontDomain = this.configService.get<string>(
      'CLOUDFRONT_DOMAIN',
      '',
    );
  }

  async upload(sessionId: string, html: string): Promise<string> {
    const key = `snapshots/${sessionId}.html`;

    await this.s3.send(
      new PutObjectCommand({
        Bucket: this.bucket,
        Key: key,
        Body: html,
        ContentType: 'text/html; charset=utf-8',
        CacheControl: 'public, max-age=259200',
      }),
    );

    const url = this.cloudfrontDomain
      ? `https://${this.cloudfrontDomain}/${key}`
      : `https://${this.bucket}.s3.amazonaws.com/${key}`;

    this.logger.log(`Snapshot uploaded: ${url}`);
    return url;
  }

  async delete(snapshotUrl: string): Promise<void> {
    const key = this.extractKey(snapshotUrl);
    if (!key) {
      this.logger.warn(`Could not extract S3 key from URL: ${snapshotUrl}`);
      return;
    }

    try {
      await this.s3.send(
        new DeleteObjectCommand({
          Bucket: this.bucket,
          Key: key,
        }),
      );
      this.logger.log(`Snapshot deleted: ${key}`);
    } catch {
      this.logger.warn(`Failed to delete snapshot: ${key}`);
    }
  }

  async exists(sessionId: string): Promise<boolean> {
    const key = `snapshots/${sessionId}.html`;
    try {
      await this.s3.send(
        new HeadObjectCommand({
          Bucket: this.bucket,
          Key: key,
        }),
      );
      return true;
    } catch {
      return false;
    }
  }

  private extractKey(url: string): string | null {
    const match = url.match(/snapshots\/[\w-]+\.html$/);
    return match ? match[0] : null;
  }
}
