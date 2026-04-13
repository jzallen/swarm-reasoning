import {
  Controller,
  Post,
  Get,
  Param,
  ParseUUIDPipe,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { CreateSessionUseCase, GetSessionUseCase } from '../../application/use-cases';

@Controller('sessions')
export class SessionController {
  constructor(
    private readonly createSessionUseCase: CreateSessionUseCase,
    private readonly getSessionUseCase: GetSessionUseCase,
  ) {}

  @Post()
  @HttpCode(HttpStatus.CREATED)
  async createSession() {
    const session = await this.createSessionUseCase.execute();
    return {
      sessionId: session.sessionId,
      status: session.status,
      createdAt: session.createdAt.toISOString(),
      frozenAt: session.frozenAt?.toISOString() ?? null,
      expiresAt: session.expiresAt?.toISOString() ?? null,
      snapshotUrl: session.snapshotUrl ?? null,
    };
  }

  @Get(':sessionId')
  async getSession(@Param('sessionId', ParseUUIDPipe) sessionId: string) {
    const session = await this.getSessionUseCase.execute(sessionId);
    return {
      sessionId: session.sessionId,
      status: session.status,
      claim: session.claim ?? null,
      createdAt: session.createdAt.toISOString(),
      frozenAt: session.frozenAt?.toISOString() ?? null,
      expiresAt: session.expiresAt?.toISOString() ?? null,
      snapshotUrl: session.snapshotUrl ?? null,
    };
  }
}
