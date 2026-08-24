<?php

namespace App\Filament\Resources;

use App\Filament\Resources\DcaScheduleResource\Pages;
use App\Models\DcaSchedule;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Tables;
use Filament\Tables\Table;

class DcaScheduleResource extends ReadOnlyResource
{
    protected static ?string $model = DcaSchedule::class;

    protected static ?string $navigationIcon = 'heroicon-o-clock';

    protected static ?string $navigationLabel = 'DCA расписания';

    protected static ?string $modelLabel = 'DCA расписание';

    protected static ?string $pluralModelLabel = 'DCA расписания';

    protected static ?string $navigationGroup = 'Торговля';

    protected static ?int $navigationSort = 4;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('currency')
                    ->label('Валюта')
                    ->disabled(),
                Forms\Components\TextInput::make('rub_amount')
                    ->label('Сумма, RUB')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('interval_days')
                    ->label('Интервал (дни)')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('next_run')
                    ->label('Следующий запуск')
                    ->disabled(),
                Forms\Components\TextInput::make('runs_total')
                    ->label('Выполнено')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('runs_limit')
                    ->label('Лимит запусков')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('status')
                    ->label('Статус')
                    ->disabled(),
                Forms\Components\TextInput::make('crypto_address')
                    ->label('Крипто адрес')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('created_at')
                    ->label('Создано')
                    ->disabled(),
            ]);
    }

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('id', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('id')
                    ->label('#')
                    ->sortable(),
                Tables\Columns\TextColumn::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('currency')
                    ->label('Валюта')
                    ->badge(),
                Tables\Columns\TextColumn::make('rub_amount')
                    ->label('RUB за раз')
                    ->numeric(2)
                    ->sortable(),
                Tables\Columns\TextColumn::make('interval_days')
                    ->label('Каждые N дней')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('next_run')
                    ->label('След. запуск')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
                Tables\Columns\TextColumn::make('runs_total')
                    ->label('Выполнено')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('runs_limit')
                    ->label('Лимит')
                    ->numeric()
                    ->toggleable(),
                Tables\Columns\TextColumn::make('status')
                    ->label('Статус')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'active' => 'success',
                        'paused' => 'warning',
                        'completed' => 'info',
                        'cancelled' => 'danger',
                        default => 'gray',
                    })
                    ->sortable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('Создано')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('status')
                    ->label('Статус')
                    ->options([
                        'active' => 'active',
                        'paused' => 'paused',
                        'completed' => 'completed',
                        'cancelled' => 'cancelled',
                    ]),
                Tables\Filters\SelectFilter::make('currency')
                    ->label('Валюта')
                    ->options([
                        'BTC' => 'BTC',
                        'LTC' => 'LTC',
                        'USDT' => 'USDT',
                        'ETH' => 'ETH',
                    ]),
            ])
            ->actions([
                Tables\Actions\ViewAction::make(),
            ])
            ->bulkActions([]);
    }

    public static function canCreate(): bool
    {
        return false;
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListDcaSchedules::route('/'),
        ];
    }
}
