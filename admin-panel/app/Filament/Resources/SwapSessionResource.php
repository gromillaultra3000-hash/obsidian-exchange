<?php

namespace App\Filament\Resources;

use App\Filament\Resources\SwapSessionResource\Pages;
use App\Models\SwapSession;
use Filament\Forms;
use Filament\Forms\Form;
use Filament\Tables;
use Filament\Tables\Table;

class SwapSessionResource extends ReadOnlyResource
{
    protected static ?string $model = SwapSession::class;

    protected static ?string $navigationIcon = 'heroicon-o-arrows-right-left';

    protected static ?string $navigationLabel = 'Свопы';

    protected static ?string $modelLabel = 'своп';

    protected static ?string $pluralModelLabel = 'свопы';

    protected static ?string $navigationGroup = 'Торговля';

    protected static ?int $navigationSort = 3;

    public static function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\TextInput::make('user_id')
                    ->label('User ID')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('web_user_id')
                    ->label('Web User ID')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('coin_from')
                    ->label('Монета (откуда)')
                    ->disabled(),
                Forms\Components\TextInput::make('coin_to')
                    ->label('Монета (куда)')
                    ->disabled(),
                Forms\Components\TextInput::make('amount_from')
                    ->label('Сумма (откуда)')
                    ->numeric()
                    ->disabled(),
                Forms\Components\TextInput::make('provider')
                    ->label('Провайдер')
                    ->disabled(),
                Forms\Components\TextInput::make('status')
                    ->label('Статус')
                    ->disabled(),
                Forms\Components\TextInput::make('session_token')
                    ->label('Токен сессии')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('address_to')
                    ->label('Адрес назначения')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('deposit_address')
                    ->label('Депозитный адрес')
                    ->disabled()
                    ->columnSpanFull(),
                Forms\Components\TextInput::make('trocador_id')
                    ->label('Trocador ID')
                    ->disabled(),
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
                Tables\Columns\TextColumn::make('coin_from')
                    ->label('Из')
                    ->badge(),
                Tables\Columns\TextColumn::make('coin_to')
                    ->label('В')
                    ->badge(),
                Tables\Columns\TextColumn::make('amount_from')
                    ->label('Сумма')
                    ->numeric(8)
                    ->sortable(),
                Tables\Columns\TextColumn::make('provider')
                    ->label('Провайдер')
                    ->badge()
                    ->toggleable(),
                Tables\Columns\TextColumn::make('trocador_id')
                    ->label('Trocador ID')
                    ->limit(16)
                    ->toggleable(),
                Tables\Columns\TextColumn::make('status')
                    ->label('Статус')
                    ->badge()
                    ->color(fn (string $state): string => match ($state) {
                        'completed' => 'success',
                        'exchanging' => 'info',
                        'awaiting_deposit' => 'warning',
                        'created' => 'gray',
                        'failed' => 'danger',
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
                        'created' => 'created',
                        'awaiting_deposit' => 'awaiting_deposit',
                        'exchanging' => 'exchanging',
                        'completed' => 'completed',
                        'failed' => 'failed',
                    ]),
                Tables\Filters\SelectFilter::make('provider')
                    ->label('Провайдер')
                    ->options([
                        'trocador' => 'trocador',
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
            'index' => Pages\ListSwapSessions::route('/'),
        ];
    }
}
