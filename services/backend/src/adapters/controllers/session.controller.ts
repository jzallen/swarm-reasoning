import {
  Controller,
  Post,
  Get,
  Param,
  ParseUUIDPipe,
  HttpCode,
  HttpStatus,
} from '@nestjs/common';
import { CreateSessionUseCase, GetSessionUseCase } from '@app/use-cases';
import { SessionPresenter } from '../presenters/session.presenter';

@Controller('sessions')
export class SessionController {
  constructor(
    private readonly createSessionUseCase: CreateSessionUseCase,
    private readonly getSessionUseCase: GetSessionUseCase,
    private readonly sessionPresenter: SessionPresenter,
  ) {}

  @Post()
  @HttpCode(HttpStatus.CREATED)
  async createSession() {
    const session = await this.createSessionUseCase.execute();
    return this.sessionPresenter.format(session);
  }

  @Get(':sessionId')
  async getSession(@Param('sessionId', ParseUUIDPipe) sessionId: string) {
    const session = await this.getSessionUseCase.execute(sessionId);
    return this.sessionPresenter.format(session);
  }
}
